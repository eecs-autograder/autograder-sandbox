import os
import subprocess
import tarfile
import tempfile
from typing import List
import uuid

import redis


SANDBOX_HOME_DIR_NAME = '/home/autograder'
SANDBOX_WORKING_DIR_NAME = os.path.join(SANDBOX_HOME_DIR_NAME, 'working_dir')
SANDBOX_USERNAME = 'autograder'
SANDBOX_DOCKER_IMAGE = os.environ.get('SANDBOX_DOCKER_IMAGE', 'jameslp/autograder-sandbox')


class AutograderSandbox:
    """
    This class wraps Docker functionality to provide an interface for
    running untrusted programs in a secure, isolated environment.

    Docker documentation and installation instructions can be
    found at: https://www.docker.com/

    Instances of this class are intended to be used with a context
    manager. The underlying docker container to be used is created and
    destroyed when the context manager is entered and exited,
    respectively.
    """

    def __init__(self, name: str=None, allow_network_access: bool=False,
                 environment_variables: dict=None, debug=False) -> None:
        """
        :param name: A human-readable name that can be used to identify
            this sandbox instance. This value must be unique across all
            sandbox instances, otherwise starting the sandbox will fail.
            If no value is specified, a random name will be generated
            automatically.

        :param allow_network_access: When True, programs running inside
            the sandbox will have unrestricted access to external
            IP addresses. When False, programs will not be able
            to contact any external IPs.

        :param environment_variables: A dictionary of (variable_name:
            value) pairs that should be set as environment variables
            inside the sandbox.

        :param debug: Whether to print additional debugging information.
        """
        if name is None:
            self._name = 'sandbox-{}'.format(uuid.uuid4().hex)
        else:
            self._name = name

        self._linux_uid = _get_next_linux_uid()

        self._allow_network_access = allow_network_access

        self._environment_variables = environment_variables

        self._is_running = False

        self.debug = debug

    def __enter__(self):
        self._create_and_start()
        return self

    def __exit__(self, *args):
        self._destroy()

    def reset(self) -> None:
        """
        Destroys, re-creates, and restarts the sandbox.
        """
        self._destroy()
        self._create_and_start()

    def _create_and_start(self):
        create_args = [
            'docker', 'run',
            '--name=' + self.name,
            '-i',  # Run in interactive mode (for input redirection)
            '-t',  # Allocate psuedo tty
            '-d',  # Detached
        ]

        if not self.allow_network_access:
            # Create the container without a network stack.
            create_args += ['--net', 'none']

        if self.environment_variables:
            for key, value in self.environment_variables.items():
                create_args += [
                    '-e', "{}={}".format(key, value)
                ]

        create_args.append(SANDBOX_DOCKER_IMAGE)  # Image to use

        subprocess.check_call(create_args, timeout=10)
        try:
            self.run_command(
                ['usermod', '-u', str(self._linux_uid), SANDBOX_USERNAME],
                as_root=True, raise_on_failure=True)
        except subprocess.CalledProcessError:
            self._destroy()
            raise

        self._is_running = True

    def _destroy(self):
        subprocess.check_call(['docker', 'stop', self.name])
        self._is_running = False
        subprocess.check_call(['docker', 'rm', self.name])

    @property
    def name(self) -> str:
        '''
        The name used to identify this sandbox. (Read only)
        '''
        return self._name

    @property
    def allow_network_access(self) -> bool:
        '''
        Whether network access is allowed by this sandbox.
        If an attempt to set this value is made while the sandbox is
        running, ValueError will be raised.
        '''
        return self._allow_network_access

    @allow_network_access.setter
    def allow_network_access(self, value: bool):
        """
        Raises ValueError if this sandbox instance is currently running.
        """
        if self._is_running:
            raise ValueError(
                "Cannot change network access settings on a running sandbox")

        self._allow_network_access = value

    @property
    def environment_variables(self) -> dict:
        '''
        A dictionary of environment variables to be set inside the
        sandbox (Read only).
        '''
        if not self._environment_variables:
            return {}

        return dict(self._environment_variables)

    def run_command(self,
                    args: List[str],
                    input_content: str=None,
                    timeout: int=None,
                    max_num_processes: int=None,
                    max_stack_size: int=None,
                    max_virtual_memory: int=None,
                    as_root: bool=False,
                    raise_on_failure: bool=False) -> 'SubprocessRunner':
        """
        Runs a command inside the sandbox and returns information about
        it.

        :param args: A list of strings that specify which command should
            be run inside the sandbox.

        :param input_content: A string whose contents should be passed to
            the command's standard input stream.

        :param timeout: A time limit in seconds.

        :param max_num_processes: The maximum number of processes the
            command is allowed to spawn.

        :param max_stack_size: The maximum stack size, in bytes, allowed
            for the command.

        :param max_virtual_memory: The maximum amount of memory, in
            bytes, allowed for the command.

        :param as_root: Whether to run the command as a root user.

        :param raise_on_failure: If True, subprocess.CalledProcessError
            will be raised if the command exits with nonzero status.
        """
        cmd = ['docker', 'exec', '-i']
        cmd.append(self.name)

        cmd.append('cmd_runner.py')

        if max_num_processes is not None:
            cmd += ['--max_num_processes', str(max_num_processes)]

        if max_stack_size is not None:
            cmd += ['--max_stack_size', str(max_stack_size)]

        if max_virtual_memory is not None:
            cmd += ['--max_virtual_memory', str(max_virtual_memory)]

        if not as_root:
            cmd += ['--linux_user_id', str(self._linux_uid)]

        cmd += args

        if self.debug:
            print('running: {}'.format(cmd), flush=True)

        if input_content is None:
            input_content = ''
        return SubprocessRunner(cmd,
                                timeout=timeout,
                                raise_on_failure=raise_on_failure,
                                stdin_content=input_content,
                                debug=self.debug)

    def add_files(self, *filenames: str):
        """
        Copies the specified files into the working directory of this
        sandbox.
        The filenames specified can be absolute paths or relative paths
        to the current working directory.
        """
        with tempfile.TemporaryFile() as f, \
                tarfile.TarFile(fileobj=f, mode='w') as tar_file:
            for filename in filenames:
                tar_file.add(filename, arcname=os.path.basename(filename))

            f.seek(0)
            subprocess.check_call(
                ['docker', 'cp', '-',
                 self.name + ':' + SANDBOX_WORKING_DIR_NAME],
                stdin=f)
            self._chown_files(
                [os.path.basename(filename) for filename in filenames])

    def add_and_rename_file(self, filename: str, new_filename: str) -> None:
        """
        Copies the specified file into the working directory of this
        sandbox and renames it to new_filename.
        """
        dest = os.path.join(
            self.name + ':' + SANDBOX_WORKING_DIR_NAME,
            new_filename)
        subprocess.check_call(['docker', 'cp', filename, dest])
        self._chown_files([new_filename])

    def _chown_files(self, filenames):
        chown_cmd = [
            'chown', '{}:{}'.format(SANDBOX_USERNAME, SANDBOX_USERNAME)]
        chown_cmd += filenames
        self.run_command(chown_cmd, as_root=True)


# TODO: Once upgraded to Python 3.5, replace call() with the
# new subprocess.run() method.
class SubprocessRunner:
    """
    Convenience wrapper for calling a subprocess and retrieving the data
    we usually need.
    Avoid using this class directly other than for reading results, as
    it will likely be replaced in future releases.
    """

    def __init__(self, program_args, **kwargs):
        self._args = program_args
        self._timeout = kwargs.get('timeout', None)
        self._stdin_content = kwargs.get('stdin_content', '')
        self._merge_stdout_and_stderr = kwargs.get(
            'merge_stdout_and_stderr', False)
        if kwargs.get('raise_on_failure', False):
            self._subprocess_method = subprocess.check_call
        else:
            self._subprocess_method = subprocess.call

        self._timed_out = False
        self._return_code = None
        self._stdout = None
        self._stderr = None

        self.debug = kwargs.get('debug', False)

        self._run()

    @property
    def timed_out(self) -> bool:
        return self._timed_out

    @property
    def return_code(self) -> int:
        return self._return_code

    @property
    def stdout(self) -> str:
        return self._stdout

    @property
    def stderr(self) -> str:
        return self._stderr

    def _run(self):
        try:
            with tempfile.TemporaryFile() as stdin_content, \
                    tempfile.TemporaryFile() as stdout_dest, \
                    tempfile.TemporaryFile() as stderr_dest:

                stdin_content.write(self._stdin_content.encode('utf-8'))
                stdin_content.seek(0)

                try:
                    self._return_code = self._subprocess_method(
                        self._args,
                        stdin=stdin_content,
                        stdout=stdout_dest,
                        stderr=stderr_dest,
                        timeout=self._timeout
                    )
                    if self.debug:
                        print("Finished running: ", self._args, flush=True)
                finally:
                    stdout_dest.seek(0)
                    stderr_dest.seek(0)
                    self._stdout = stdout_dest.read().decode('utf-8')
                    self._stderr = stderr_dest.read().decode('utf-8')

                    if self.debug:
                        print("Return code: ", self._return_code, flush=True)
                        print(self._stdout, flush=True)
                        print(self._stderr, flush=True)
        except subprocess.TimeoutExpired:
            self._timed_out = True
        except UnicodeDecodeError:
            msg = ("Error reading program output: "
                   "non-unicode characters detected")
            self._stdout = msg
            self._stderr = msg


_REDIS_SETTINGS = {
    'host': os.environ.get('AG_REDIS_HOST', 'localhost'),
    'port': os.environ.get('AG_REDIS_PORT', '6379')
}

_NEXT_UID_KEY = 'sandbox_next_uid'


def _get_next_linux_uid():
    redis_conn = redis.StrictRedis(**_REDIS_SETTINGS)
    redis_conn.setnx('sandbox_next_uid', 2000)
    return redis_conn.incr(_NEXT_UID_KEY)
