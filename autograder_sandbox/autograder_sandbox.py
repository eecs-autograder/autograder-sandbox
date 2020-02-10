import json
import os
import subprocess
import tarfile
import tempfile
import uuid
from io import FileIO
from typing import List, Union

import redis


SANDBOX_HOME_DIR_NAME = '/home/autograder'
SANDBOX_WORKING_DIR_NAME = os.path.join(SANDBOX_HOME_DIR_NAME, 'working_dir')
SANDBOX_USERNAME = 'autograder'
SANDBOX_DOCKER_IMAGE = os.environ.get('SANDBOX_DOCKER_IMAGE', 'jameslp/ag-ubuntu-16:1')

SANDBOX_PIDS_LIMIT = os.environ.get('SANDBOX_PIDS_LIMIT', 512)
SANDBOX_MEM_LIMIT = os.environ.get('SANDBOX_MEM_LIMIT', 8 * 10 ** 9)
SANDBOX_MIN_FALLBACK_TIMEOUT = os.environ.get('SANDBOX_MIN_FALLBACK_TIMEOUT', 60)

CMD_RUNNER_PATH = '/usr/local/bin/cmd_runner.py'


class SandboxCommandError(Exception):
    """
    An exception to be raised when a call to AutograderSandbox.run_command
    doesn't finish normally.
    """
    pass


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
                 pids_limit: int=SANDBOX_PIDS_LIMIT,
                 memory_limit: Union[int, str]=SANDBOX_MEM_LIMIT,
                 min_fallback_timeout: int=SANDBOX_MIN_FALLBACK_TIMEOUT,
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

        :param pids_limit: Passed to "docker create" with the
            --pids-limit flag. This will limit the number of processes
            that can be created.
            See https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v1/pids.html
            for more information on limiting pids with cgroups.

            We recommend leaving this value set to the default of 512
            and using the max_num_processes argument to run_command
            if you want to impose a strict limit on a particular command.

            The default value for this parameter can be changed by
            setting the SANDBOX_PIDS_LIMIT environment variable.

        :param memory_limit: Passed to "docker create" with the --memory,
            --memory-swap, and --oom-kill-disable arguments. This will
            limit the amount of memory that processes running in the
            sandbox can use.

            We choose to disable the OOM killer to prevent the sandbox's
            main process from being killed by the OOM killer (which would
            cause the whole container to exit). This means, however, that
            a command that hits the memory limit may time out.

            In general we recommend setting this value as high as is safe
            for your host machine and additionally using the max_virtual_memory
            argument to run_command to set a tighter limit on the command's
            address space size.

            The default value for this parameter can be changed by
            setting the SANDBOX_MEM_LIMIT environment variable.

            See https://docs.docker.com/config/containers/resource_constraints/
                    #limit-a-containers-access-to-memory
            for more information.

        :param min_fallback_timeout: The timeout argument to run_command
            is primarily enforced by cmd_runner.py. When that argument is
            not None, a timeout of either twice the timeout argument to
            run_command or this value, whichever is larger, will be applied
            to the subprocess call to cmd_runner.py itself.

            The default value for this parameter can be changed by
            setting the SANDBOX_MIN_FALLBACK_TIMEOUT environment variable.

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
        self._pids_limit = pids_limit
        self._memory_limit = memory_limit
        self._min_fallback_timeout = min_fallback_timeout
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

            '--pids-limit', str(self._pids_limit),
            '--memory', str(self._memory_limit),
            '--memory-swap', str(self._memory_limit),
            '--oom-kill-disable',
        ]

        if not self.allow_network_access:
            # Create the container without a network stack.
            create_args += ['--net', 'none']

        if self.environment_variables:
            for key, value in self.environment_variables.items():
                create_args += [
                    '-e', "{}={}".format(key, value)
                ]

        # Override any CMD or ENTRYPOINT directives used in custom images.
        # This restriction is in place to avoid situations where a custom
        # entrypoint exits prematurely, therefore stopping the container.
        # https://docs.docker.com/engine/reference/run/#overriding-dockerfile-image-defaults
        create_args += ['--entrypoint', '']
        create_args.append(self.docker_image)  # Image to use
        create_args.append('/bin/bash')

        subprocess.check_call(create_args, timeout=self._container_create_timeout)
        try:
            subprocess.run(
                ['docker', 'exec', '-i', self.name, 'usermod', '-u',
                 str(self._linux_uid), SANDBOX_USERNAME],
                check=True)

            cmd_runner_source = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'docker-image-setup',
                'cmd_runner.py'
            )
            subprocess.run(
                ['docker', 'cp', cmd_runner_source, '{}:{}'.format(self.name, CMD_RUNNER_PATH)],
                check=True)
            subprocess.run(
                ['docker', 'exec', '-i', self.name, 'chmod', '555', CMD_RUNNER_PATH],
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
        """
        The name used to identify this sandbox. (Read only)
        """
        return self._name

    @property
    def docker_image(self) -> str:
        """
        The name of the docker image to create the sandbox from.
        """
        return self._docker_image

    @property
    def allow_network_access(self) -> bool:
        """
        Whether network access is allowed by this sandbox.
        If an attempt to set this value is made while the sandbox is
        running, ValueError will be raised.
        """
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
        """
        A dictionary of environment variables to be set inside the
        sandbox (Read only).
        """
        if not self._environment_variables:
            return {}

        return dict(self._environment_variables)

    def run_command(self,
                    args: List[str],
                    max_num_processes: int=None,
                    max_stack_size: int=None,
                    max_virtual_memory: int=None,
                    as_root: bool=False,
                    stdin: FileIO=None,
                    timeout: int=None,
                    check: bool=False,
                    truncate_stdout: int=None,
                    truncate_stderr: int=None) -> 'CompletedCommand':
        """
        Runs a command inside the sandbox and returns the results.

        :param args: A list of strings that specify which command should
            be run inside the sandbox.

        :param max_num_processes: The maximum number of processes the
            command is allowed to spawn.

        :param max_stack_size: The maximum stack size, in bytes, allowed
            for the command.

        :param max_virtual_memory: The maximum amount of memory, in
            bytes, allowed for the command.

        :param as_root: Whether to run the command as a root user.

        :param stdin: A file object to be redirected as input to the
            command's stdin. If this is None, /dev/null is sent to the
            command's stdin.

        :param timeout: The time limit for the command.

        :param check: Causes CalledProcessError to be raised if the
            command exits nonzero or times out.

        :param truncate_stdout: When not None, stdout from the command
            will be truncated after this many bytes.

        :param truncate_stderr: When not None, stderr from the command
            will be truncated after this many bytes.
        """
        cmd = ['docker', 'exec', '-i', self.name, CMD_RUNNER_PATH]

        if stdin is None:
            cmd.append('--stdin_devnull')

        if max_num_processes is not None:
            cmd += ['--max_num_processes', str(max_num_processes)]

        if max_stack_size is not None:
            cmd += ['--max_stack_size', str(max_stack_size)]

        if max_virtual_memory is not None:
            cmd += ['--max_virtual_memory', str(max_virtual_memory)]

        if timeout is not None:
            cmd += ['--timeout', str(timeout)]

        if truncate_stdout is not None:
            cmd += ['--truncate_stdout', str(truncate_stdout)]

        if truncate_stderr is not None:
            cmd += ['--truncate_stderr', str(truncate_stderr)]

        if not as_root:
            cmd += ['--linux_user_id', str(self._linux_uid)]

        cmd += args

        if self.debug:
            print('running: {}'.format(cmd), flush=True)

        with tempfile.TemporaryFile() as runner_stdout, tempfile.TemporaryFile() as runner_stderr:
            fallback_timeout = (
                max(timeout * 2, self._min_fallback_timeout) if timeout is not None else None)
            try:
                subprocess.run(cmd, stdin=stdin, stdout=runner_stdout, stderr=runner_stderr,
                               check=True, timeout=fallback_timeout)
                runner_stdout.seek(0)

                json_len = int(runner_stdout.readline().decode().rstrip())
                results_json = json.loads(runner_stdout.read(json_len).decode())

                stdout_len = int(runner_stdout.readline().decode().rstrip())
                stdout = tempfile.NamedTemporaryFile()
                for chunk in _chunked_read(runner_stdout, stdout_len):
                    stdout.write(chunk)
                stdout.seek(0)

                stderr_len = int(runner_stdout.readline().decode().rstrip())
                stderr = tempfile.NamedTemporaryFile()
                for chunk in _chunked_read(runner_stdout, stderr_len):
                    stderr.write(chunk)
                stderr.seek(0)

                result = CompletedCommand(return_code=results_json['return_code'],
                                          timed_out=results_json['timed_out'],
                                          stdout=stdout,
                                          stderr=stderr,
                                          stdout_truncated=results_json['stdout_truncated'],
                                          stderr_truncated=results_json['stderr_truncated'])

                if (result.return_code != 0 or results_json['timed_out']) and check:
                    raise subprocess.CalledProcessError(
                        result.return_code, cmd,
                        output=result.stdout, stderr=result.stderr)

                return result
            except subprocess.TimeoutExpired as e:
                stdout_len = runner_stdout.tell()
                runner_stdout.seek(0)
                stdout = tempfile.NamedTemporaryFile()
                for chunk in _chunked_read(runner_stdout, stdout_len):
                    stdout.write(chunk)
                stdout.seek(0)

                stderr_len = runner_stderr.tell()
                runner_stderr.seek(0)
                stderr = tempfile.NamedTemporaryFile()
                stderr.write(b'The command exceeded the fallback timeout. '
                             b'If this occurs frequently, contact your system administrator.\n')
                for chunk in _chunked_read(runner_stderr, stderr_len):
                    stderr.write(chunk)
                stderr.seek(0)

                return CompletedCommand(
                    return_code=None,
                    timed_out=True,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_truncated=False,
                    stderr_truncated=True,
                )
            except subprocess.CalledProcessError as e:
                runner_stdout.seek(0)
                runner_stderr.seek(0)
                raise SandboxCommandError(
                    runner_stdout.read().decode('utf-8', 'surrogateescape')
                    + '\n'
                    + runner_stderr.read().decode('utf-8', 'surrogateescape')
                ) from e

    def add_files(self, *filenames: str, owner: str=SANDBOX_USERNAME, read_only: bool=False):
        """
        Copies the specified files into the working directory of this
        sandbox.
        The filenames specified can be absolute paths or relative paths
        to the current working directory.

        :param owner: The name of a user who should be granted ownership of
            the newly added files.
            Must be either autograder_sandbox.SANDBOX_USERNAME or 'root',
            otherwise ValueError will be raised.
        :param read_only: If true, the new files' permissions will be set to
            read-only.
        """
        if owner != SANDBOX_USERNAME and owner != 'root':
            raise ValueError('Invalid value for parameter "owner": {}'.format(owner))

        with tempfile.TemporaryFile() as f, \
                tarfile.TarFile(fileobj=f, mode='w') as tar_file:
            for filename in filenames:
                tar_file.add(filename, arcname=os.path.basename(filename))

            f.seek(0)
            subprocess.check_call(
                ['docker', 'cp', '-',
                 self.name + ':' + SANDBOX_WORKING_DIR_NAME],
                stdin=f)

            file_basenames = [os.path.basename(filename) for filename in filenames]
            if owner == SANDBOX_USERNAME:
                self._chown_files(file_basenames)

            if read_only:
                chmod_cmd = ['chmod', '444'] + file_basenames
                self.run_command(chmod_cmd, as_root=True)

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


# Generator that reads amount_to_read bytes from file_obj, yielding
# one chunk at a time.
def _chunked_read(file_obj, amount_to_read, chunk_size=1024 * 16):
    num_reads = amount_to_read // chunk_size
    for i in range(num_reads):
        yield file_obj.read(chunk_size)

    remainder = amount_to_read % chunk_size
    if remainder:
        yield file_obj.read(remainder)


class CompletedCommand:
    def __init__(self, return_code: int, stdout: FileIO, stderr: FileIO, timed_out: bool,
                 stdout_truncated: bool, stderr_truncated: bool):
        """
        :param return_code: The return code of the command,
            or None if the command timed out.
        :param stdout: A file object containing the
            stdout content of the command.
        :param stderr: A file object containing the
            stderr content of the command.
        :param timed_out: Whether the command exceeded the time limit.
        :param stdout_truncated: Whether stdout was truncated.
        :param stderr_truncated: Whether stderr was truncated.
        """
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.stdout_truncated = stdout_truncated
        self.stderr_truncated = stderr_truncated


_REDIS_SETTINGS = {
    'host': os.environ.get('AG_REDIS_HOST', 'localhost'),
    'port': os.environ.get('AG_REDIS_PORT', '6379')
}

_NEXT_UID_KEY = 'sandbox_next_uid'


def _get_next_linux_uid():
    redis_conn = redis.StrictRedis(**_REDIS_SETTINGS)
    redis_conn.setnx('sandbox_next_uid', 2000)
    return redis_conn.incr(_NEXT_UID_KEY)
