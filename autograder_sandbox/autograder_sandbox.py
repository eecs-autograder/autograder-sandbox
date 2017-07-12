import json
import os
import subprocess
import tarfile
import tempfile
import uuid
from typing import List

import redis  # type: ignore

VERSION = '2.0.2'

SANDBOX_HOME_DIR_NAME = '/home/autograder'
SANDBOX_WORKING_DIR_NAME = os.path.join(SANDBOX_HOME_DIR_NAME, 'working_dir')
SANDBOX_USERNAME = 'autograder'
SANDBOX_DOCKER_IMAGE = os.environ.get('SANDBOX_DOCKER_IMAGE',
                                      'jameslp/autograder-sandbox:{}'.format(VERSION))


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

    def __init__(self, name: str=None,
                 docker_image: str=SANDBOX_DOCKER_IMAGE,
                 allow_network_access: bool=False,
                 environment_variables: dict=None,
                 container_create_timeout: int=None,
                 debug=False) -> None:
        """
        :param name: A human-readable name that can be used to identify
            this sandbox instance. This value must be unique across all
            sandbox instances, otherwise starting the sandbox will fail.
            If no value is specified, a random name will be generated
            automatically.

        :param docker_image: The name of the docker image to create the
            sandbox from. Note that in order to function properly, all
            custom docker images must extend jameslp/autograder-sandbox.
            This value takes precedence over the value of the
            environment variable SANDBOX_DOCKER_IMAGE.

        :param allow_network_access: When True, programs running inside
            the sandbox will have unrestricted access to external
            IP addresses. When False, programs will not be able
            to contact any external IPs.

        :param environment_variables: A dictionary of (variable_name:
            value) pairs that should be set as environment variables
            inside the sandbox.

        :param container_create_timeout: A time limit to be placed on
            creating the underlying Docker container for this sandbox.
            If the time limit is exceeded, subprocess.CalledProcessError
            will be raised. A value of None indicates no time limit.

        :param debug: Whether to print additional debugging information.
        """
        if name is None:
            self._name = 'sandbox-{}'.format(uuid.uuid4().hex)
        else:
            self._name = name

        self._docker_image = docker_image
        self._linux_uid = _get_next_linux_uid()
        self._allow_network_access = allow_network_access
        self._environment_variables = environment_variables
        self._is_running = False
        self._container_create_timeout = container_create_timeout
        self.debug = debug

    def __enter__(self):
        self._create_and_start()
        return self

    def __exit__(self, *args):
        self._destroy()

    def reset(self) -> None:
        """
        Destroys, re-creates, and restarts the sandbox. As a side
        effect, this will effectively kill any processes running inside
        the sandbox and reset the sandbox's filesystem.
        """
        self._destroy()
        self._create_and_start()

    def restart(self):
        """
        Restarts the sandbox without destroying it. As a side effect,
        this will kill any processes running inside the sandbox.

        IMPORTANT: It is strongly recommended that you call this method
        after a command run by run_command times out.
        """
        self._stop()
        subprocess.check_call(['docker', 'start', self.name])

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

        create_args.append(self.docker_image)  # Image to use

        subprocess.check_call(create_args,
                              timeout=self._container_create_timeout)
        try:
            subprocess.run(
                ['docker', 'exec', '-i', self.name, 'usermod', '-u',
                 str(self._linux_uid), SANDBOX_USERNAME],
                check=True)
        except subprocess.CalledProcessError as e:
            if self.debug:
                print(e.stdout)
                print(e.stderr)

            self._destroy()
            raise

        self._is_running = True

    def _destroy(self):
        self._stop()
        subprocess.check_call(['docker', 'rm', self.name])
        self._is_running = False

    def _stop(self):
        subprocess.check_call(['docker', 'stop', '--time', '1', self.name])

    @property
    def name(self) -> str:
        '''
        The name used to identify this sandbox. (Read only)
        '''
        return self._name

    @property
    def docker_image(self) -> str:
        '''
        The name of the docker image to create the sandbox from.
        '''
        return self._docker_image

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
                    max_num_processes: int=None,
                    max_stack_size: int=None,
                    max_virtual_memory: int=None,
                    as_root: bool=False,
                    input: str='',
                    timeout: int=None,
                    check: bool=False,
                    encoding: str='utf-8',
                    errors: str='backslashreplace') -> subprocess.CompletedProcess:
        """
        Runs a command inside the sandbox and returns a
        subprocess.CompletedProcess object.

        *Note*: The stdout and
        stderr fields of this object are modified so as to always be
        strings.

        *New in 2.0.0*: This function raises subprocess.TimeoutExpired
        if timeout is exceeded.

        :param args: A list of strings that specify which command should
            be run inside the sandbox.

        :param max_num_processes: The maximum number of processes the
            command is allowed to spawn.

        :param max_stack_size: The maximum stack size, in bytes, allowed
            for the command.

        :param max_virtual_memory: The maximum amount of memory, in
            bytes, allowed for the command.

        :param as_root: Whether to run the command as a root user.

        :param input: A string to be passed as input to the command's
            stdin.
        :param timeout: The time limit for the command.
        :param check: Causes CalledProcessError to be raised if the
            command exits nonzero.

        :param encoding: The encoding to use for stdin, stdout, and
            stderr. See https://docs.python.org/3/library/codecs.html
            for valid values for this parameter.
        :param errors: The error handling policy for the specified
            encoding. See https://docs.python.org/3/library/codecs.html
            for valid values for this parameter.
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

        if timeout is not None:
            cmd += ['--timeout', str(timeout)]

        if encoding is not None:
            cmd += ['--encoding', encoding]

        if errors is not None:
            cmd += ['--encoding_error_policy', errors]

        if not as_root:
            cmd += ['--linux_user_id', str(self._linux_uid)]

        cmd += args

        if self.debug:
            print('running: {}'.format(cmd), flush=True)

        try:
            result = subprocess.run(cmd,
                                    input=input.encode(encoding, errors=errors),
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    check=True)
            results_json = json.loads(result.stdout.decode())
            result.stdout = results_json['stdout']
            result.stderr = results_json['stderr']
            result.returncode = results_json['return_code']

            if results_json['timed_out']:
                raise subprocess.TimeoutExpired(
                    cmd, timeout, output=result.stdout, stderr=result.stderr)

            if result.returncode != 0 and check:
                raise subprocess.CalledProcessError(
                    result.returncode, cmd,
                    output=result.stdout, stderr=result.stderr)

            return result
        except subprocess.CalledProcessError as e:
            print(e.stdout)
            print(e.stderr)
            raise

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


_REDIS_SETTINGS = {
    'host': os.environ.get('AG_REDIS_HOST', 'localhost'),
    'port': os.environ.get('AG_REDIS_PORT', '6379')
}

_NEXT_UID_KEY = 'sandbox_next_uid'


def _get_next_linux_uid():
    redis_conn = redis.StrictRedis(**_REDIS_SETTINGS)
    redis_conn.setnx('sandbox_next_uid', 2000)
    return redis_conn.incr(_NEXT_UID_KEY)
