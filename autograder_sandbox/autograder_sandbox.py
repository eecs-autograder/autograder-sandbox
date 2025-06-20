from typing import Any
import os
import signal
import subprocess
import tarfile
import tempfile
import traceback
import uuid
from decimal import Decimal
from typing import (IO, AnyStr, Iterator, List, Mapping, Optional, Sequence, Type)
import logging

logger = logging.getLogger(__name__)

SANDBOX_HOME_DIR_NAME = '/home/autograder'
SANDBOX_WORKING_DIR_NAME = os.path.join(SANDBOX_HOME_DIR_NAME, 'working_dir')
# KEEP UP TO DATE WITH SANDBOX_USERNAME IN cmd_runner.py
SANDBOX_USERNAME = 'autograder'
SANDBOX_DOCKER_IMAGE = os.environ.get('SANDBOX_DOCKER_IMAGE', 'eecsautograder/ubuntu22:latest')

SANDBOX_PIDS_LIMIT = int(os.environ.get('SANDBOX_PIDS_LIMIT', 512))
SANDBOX_MEM_LIMIT = os.environ.get('SANDBOX_MEM_LIMIT', '4g')
SANDBOX_CPU_CORE_LIMIT = (
    Decimal(val) if (val := os.environ.get('SANDBOX_CPU_CORE_LIMIT')) is not None else None
)

CMD_RUNNER_PATH = '/usr/local/bin/cmd_runner.py'


class CompletedCommand:
    def __init__(
        self, return_code: Optional[int],
        stdout: IO[bytes],
        stderr: IO[bytes],
        timed_out: bool,
        stdout_truncated: bool,
        stderr_truncated: bool
    ):
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


class SandboxError(Exception):
    """A base exception class for this library."""


class SandboxCommandError(SandboxError):
    """
    An exception to be raised when a call to AutograderSandbox.run_command
    with check=True exits with nonzero status or times out.
    """
    def __init__(self, cmd: List[str], result: CompletedCommand) -> None:
        """
        :param cmd: The command that was run.
        :param result: An object containing information about the run results
            of the command.
        """
        self.cmd = cmd
        self.result = result


class CriticalSandboxError(SandboxError):
    """
    An exception to be raised when critical, unexpected errors are encountered
    that require manual intervention.
    """


class SandboxNotStopped(CriticalSandboxError):
    """
    Indicates that attempting to stop a sandbox container failed and that
    manual intervention is required to stop the container.
    """


class SandboxNotDestroyed(SandboxError):
    """
    An exception to be raised when an unexpected error occurs trying to
    destroy a sandbox. Note that such an error is *not* considered critical.
    """


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

    def __init__(self, name: Optional[str] = None,
                 docker_image: str = SANDBOX_DOCKER_IMAGE,
                 allow_network_access: bool = False,
                 environment_variables: Optional[Mapping[str, str]] = None,
                 pids_limit: int = SANDBOX_PIDS_LIMIT,
                 memory_limit: str = SANDBOX_MEM_LIMIT,
                 cpu_core_limit: Optional[Decimal] = SANDBOX_CPU_CORE_LIMIT,
                 container_create_timeout: Optional[int] = None,
                 container_setup_timeout: Optional[int] = None,
                 process_reap_timeout: Optional[int] = 60,
                 container_teardown_timeout: Optional[int] = 30):
        """
        :param name: A human-readable name that can be used to identify
            this sandbox instance. This value must be unique across all
            sandbox instances, otherwise starting the sandbox will fail.
            If no value is specified, a random name will be generated
            automatically.

        :param docker_image: The name of the docker image to create the
            sandbox from. Note that in order to function properly, all
            custom docker images must extend a supported base image (see README).

            The default value for this parameter can be changed by
            setting the SANDBOX_DOCKER_IMAGE environment variable.

        :param allow_network_access: When True, programs running inside
            the sandbox will have unrestricted access to external
            IP addresses. When False, programs will not be able
            to contact any external IPs.

        :param environment_variables: A dictionary of (variable_name:
            value) pairs that should be set as environment variables
            inside the sandbox.

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

        :param memory_limit: Passed to "docker create" with the --memory
            and --memory-swap arguments. This will
            limit the amount of memory that processes running in the
            sandbox can use.

            New in version 6.0.0: This option no longer passes
            --oom-kill-disable, as that option is not supported on
            newer linux kernels with cgroups v2.

            In general we recommend setting this value as high as is safe
            for your host machine and additionally using the max_virtual_memory
            argument to run_command to set a tighter limit on the command's
            address space size.

            The default value for this parameter can be changed by
            setting the SANDBOX_MEM_LIMIT environment variable.

            See https://docs.docker.com/config/containers/resource_constraints/\
#limit-a-containers-access-to-memory
            for more information.

        :param cpu_core_limit: Passed to "docker create" with the --cpus
            argument. This will limit the number of cpu cores that processes
            running in the sandbox can use.

            See https://docs.docker.com/config/containers/resource_constraints/#cpu
            for more information.

            The default value for this parameter can be changed by setting the
            SANDBOX_CPU_CORE_LIMIT environment variable.

            New in version 6.0.0.

        :param container_create_timeout: A time limit to be placed on
            creating and starting the underlying Docker container for this sandbox.
            If the time limit is exceeded, SandboxError
            will be raised. A value of None indicates no time limit.

            We recommend a high value or None for this time limit since
            creating a container sometimes requires downloading a new
            image.

        :param container_setup_timeout: A time limit placed on individual
            steps of starting and setting up the container
            (e.g. adding the cmd_runner.py script to the container).
            If the time limit is exceeded, SandboxError
            will be raised. A value of None indicates no time limit.

            New in 6.0.0

        :param process_reap_timeout: A time limit placed on reaping a process
            tree after a command times out or when stopping a container times
            out.
            If the time limit is exceeded, SandboxError
            will be raised. A value of None indicates no time limit.

            New in 6.0.0

        :param container_teardown_timeout: A time limit placed on stopping
            and destroying the container.
            If the time limit is exceeded while stopping the container,
            the sandbox will try reaping processes in the container
            and retrying stopping the container. If the container
            does not stop then, CriticalSandboxError is raised.

            If the container is stopped but removing it fails,
            SandboxNotDestroyed is raised.

            A value of None indicates no time limit, but this is
            NOT RECOMMENDED.

            New in 6.0.0
        """
        # Used for reliably finding the container's main process.
        self._unique_id = f'sandbox-{uuid.uuid4().hex}'
        self._main_process_script = f'/{self._unique_id}-main.sh'

        if name is None:
            self._name = self._unique_id
        else:
            self._name = name

        self._docker_image = docker_image
        self._allow_network_access = allow_network_access
        self._environment_variables = environment_variables
        self._is_running = False
        self._container_create_timeout = container_create_timeout
        self._pids_limit = pids_limit
        self._memory_limit = memory_limit
        self._cpu_core_limit = cpu_core_limit

        self._container_setup_timeout = container_setup_timeout
        self._process_reap_timeout = process_reap_timeout
        self._container_teardown_timeout = container_teardown_timeout

    def __enter__(self) -> 'AutograderSandbox':
        self._create_and_start()
        return self

    def __exit__(self, *args: object) -> None:
        self._destroy()

    def reset(self) -> None:
        """
        Stops, destroys, re-creates, and restarts the sandbox. As a side
        effect, this will effectively kill any processes running inside
        the sandbox and reset the sandbox's filesystem.
        """
        self._destroy()
        self._create_and_start()

    def restart(self) -> None:
        """
        Restarts the sandbox without destroying it.
        """
        self._stop()
        _subprocess_helper(
            ['docker', 'start', self.name],
            timeout=self._container_create_timeout,
            error_msg_prefix='Error restarting container'
        )

    def _create_and_start(self) -> None:
        create_args = [
            'docker', 'create',
            '--name=' + self.name,
            '-i',  # Run in interactive mode (for input redirection)
            '-t',  # Allocate psuedo tty

            '--pids-limit', str(self._pids_limit),
            '--memory', self._memory_limit,
            '--memory-swap', self._memory_limit,
        ]

        if self._cpu_core_limit is not None:
            create_args += ['--cpus', str(self._cpu_core_limit)]

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
        create_args += ['/bin/bash', self._main_process_script]

        logger.debug(f'Creating container: {create_args}')

        # Create the container, copy our main process script (the name of which
        # contains self._unique_id) into it, then start the container.

        _subprocess_helper(
            create_args,
            timeout=self._container_create_timeout,
            error_msg_prefix=f'Error creating container {self.name}',
            reraise_as=SandboxError
        )

        with tempfile.NamedTemporaryFile() as main_proc_script_file:
            # IMPORTANT: FLUSH THE STREAM AFTER WRITING!!
            main_proc_script_file.write(b'while :\ndo read; done')
            main_proc_script_file.flush()

            _subprocess_helper(
                [
                    'docker', 'cp',
                    main_proc_script_file.name, f'{self.name}:{self._main_process_script}'
                ],
                timeout=self._container_setup_timeout,
                error_msg_prefix=f'Error adding entrypoint script to container {self.name}',
                reraise_as=SandboxError
            )

        _subprocess_helper(
            ['docker', 'start', self.name],
            timeout=self._container_create_timeout,
            error_msg_prefix=f'Error starting container {self.name}',
            reraise_as=SandboxError
        )

        # Add cmd_runner.py to the container and set its permissions.
        try:
            cmd_runner_source = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'docker-image-setup',
                'cmd_runner.py'
            )
            _subprocess_helper(
                ['docker', 'cp', cmd_runner_source, '{}:{}'.format(self.name, CMD_RUNNER_PATH)],
                timeout=self._container_setup_timeout,
                error_msg_prefix=f'Error adding cmd_runner.py to container {self.name}',
                reraise_as=SandboxError
            )
            _subprocess_helper(
                ['docker', 'exec', '-i', self.name, 'chmod', '555', CMD_RUNNER_PATH],
                timeout=self._container_setup_timeout,
                error_msg_prefix=(
                    f'Error setting cmd_runner.py permissions in container {self.name}'
                ),
                reraise_as=SandboxError
            )
        except Exception as e:
            self._destroy()
            raise

        self._is_running = True

    def _destroy(self) -> None:
        self._stop()

        # Note: Since destroying containers isn't immediately mission-critical
        # in production (the sysadmin can set up a cron job that runs docker
        # prune), we throw SandboxNotDestroyed instead of CriticalSandboxError
        _subprocess_helper(
            ['docker', 'rm', '-f', self.name],
            timeout=self._container_teardown_timeout,
            error_msg_prefix=f'Error destroying container {self.name}',
            reraise_as=SandboxNotDestroyed
        )
        self._is_running = False

    def _stop(self) -> None:
        try:
            _subprocess_helper(
                ['docker', 'stop', '--time', '10', self.name],
                timeout=self._container_teardown_timeout,
                error_msg_prefix=f'Error stopping container {self.name}'
            )
            self._is_running = False
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            try:
                self._reap(self._main_process_script)
                _subprocess_helper(
                    ['docker', 'stop', '--time', '5', self.name],
                    timeout=self._container_teardown_timeout,
                    error_msg_prefix=(
                        f'Error stopping container {self.name} after reaping proc tree'
                    )
                )
                self._is_running = False
            except Exception as fatal:
                logger.critical(
                    'An unexpected error occurred while trying to stop container '
                    f'{self.name}: {fatal}\n'
                    + traceback.format_exc()
                )
                raise SandboxNotStopped from fatal

    def _reap(self, search_for: str) -> None:
        """
        Search for the process that contains "search_for" in its command line
        arguments. search_for should be either the unique main container process
        or the unique ID included in a call to cmd_runner.py

        Finds and kills the process tree whose root is the found process.
        Does not kill the root of the tree.
        """
        try:
            result = _subprocess_helper(
                ['docker', 'run', '--rm', '--pid', 'host',
                 'jameslp/autograder-sandbox-reaper:1', search_for],
                timeout=self._process_reap_timeout,
                error_msg_prefix=f'Error reaping children of {search_for}'
            )
            logger.debug(f'reaper exited with status {result.returncode}')
            logger.debug(result.stdout)
            logger.debug(result.stderr)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            _mocking_hook('reaping_failed')
            logger.error(str(e))
            logger.error(e.stdout)
            logger.error(e.stderr)
            # Do NOT reraise an exception here so that reaping failing
            # for some random reason doesn't derail things.

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
    def allow_network_access(self, value: bool) -> None:
        """
        Raises ValueError if this sandbox instance is currently running.
        """
        if self._is_running:
            raise ValueError(
                "Cannot change network access settings on a running sandbox")

        self._allow_network_access = value

    @property
    def environment_variables(self) -> Mapping[str, str]:
        """
        A dictionary of environment variables to be set inside the
        sandbox (Read only).
        """
        if not self._environment_variables:
            return {}

        return dict(self._environment_variables)

    def run_command(self,
                    args: List[str],
                    block_process_spawn: bool = False,
                    max_stack_size: Optional[int] = None,
                    max_virtual_memory: Optional[int] = None,
                    as_root: bool = False,
                    stdin: Optional[IO[AnyStr]] = None,
                    timeout: Optional[int] = None,
                    check: bool = False,
                    truncate_stdout: Optional[int] = None,
                    truncate_stderr: Optional[int] = None) -> 'CompletedCommand':
        """
        Runs a command inside the sandbox and returns the results.

        :param args: A list of strings that specify which command should
            be run inside the sandbox.

        :param block_process_spawn: If true, prevent the command from
            spawning child processes by setting the nproc limit to 0.

        :param max_stack_size: The maximum stack size, in bytes, allowed
            for the command.

        :param max_virtual_memory: The maximum amount of memory, in
            bytes, allowed for the command.

        :param as_root: Whether to run the command as a root user.

        :param stdin: A file object to be redirected as input to the
            command's stdin. If this is None, /dev/null is sent to the
            command's stdin.

        :param timeout: The time limit for the command.

        :param check: Causes SandboxCommandError to be raised if the
            command exits nonzero or times out.

        :param truncate_stdout: When not None, stdout from the command
            will be truncated after this many bytes.

        :param truncate_stderr: When not None, stderr from the command
            will be truncated after this many bytes.
        """
        cmd_id = f'{self._unique_id}_cmd{uuid.uuid4().hex}'
        cmd = ['docker', 'exec', '-i', self.name, CMD_RUNNER_PATH, '--cmd_id', cmd_id]

        if block_process_spawn:
            cmd += ['--block_process_spawn']

        if max_stack_size is not None:
            cmd += ['--max_stack_size', str(max_stack_size)]

        if max_virtual_memory is not None:
            cmd += ['--max_virtual_memory', str(max_virtual_memory)]

        if timeout is not None:
            cmd += ['--timeout', str(timeout)]

        if as_root:
            cmd += ['--as_root']

        cmd += args

        logger.debug(f'Running: {cmd} in sandbox {self.name}')

        return_code: Optional[int] = None
        timed_out: bool = False
        with open(os.devnull) as devnull, \
                tempfile.TemporaryFile() as runner_stdout, \
                tempfile.TemporaryFile() as runner_stderr, \
                subprocess.Popen(cmd, stdin=stdin if stdin is not None else devnull,
                                 stdout=runner_stdout, stderr=runner_stderr,
                                 start_new_session=True) as docker_exec:
            try:
                return_code = docker_exec.wait(timeout=timeout)
            except subprocess.TimeoutExpired as e:
                logger.info(
                    f'Command "{cmd}" in sandbox {self.name} timed out. '
                    'Will attempt to reap process tree.'
                )
                timed_out = True
                self._reap(cmd_id)
                os.killpg(os.getpgid(docker_exec.pid), signal.SIGTERM)

                try:
                    docker_exec.communicate(None, timeout=1)
                except:  # noqa
                    # http://stackoverflow.com/questions/4789837/how-to-terminate-a-python-subprocess-launched-with-shell-true
                    os.killpg(os.getpgid(docker_exec.pid), signal.SIGKILL)

            stdout_len = runner_stdout.tell()
            if truncate_stdout is not None and runner_stdout.tell() > truncate_stdout:
                stdout_len = truncate_stdout
                stdout_truncated = True
            else:
                stdout_truncated = False

            stderr_len = runner_stderr.tell()
            if truncate_stderr is not None and runner_stderr.tell() > truncate_stderr:
                stderr_len = truncate_stderr
                stderr_truncated = True
            else:
                stderr_truncated = False

            # IMPORTANT: These calls to .seek(0) must happen *after*
            # calling .tell() on these files.
            runner_stdout.seek(0)
            runner_stderr.seek(0)

            stdout = tempfile.NamedTemporaryFile()
            for chunk in _chunked_read(runner_stdout, stdout_len):
                stdout.write(chunk)
            stdout.seek(0)

            stderr = tempfile.NamedTemporaryFile()
            for chunk in _chunked_read(runner_stderr, stderr_len):
                stderr.write(chunk)
            stderr.seek(0)

            result = CompletedCommand(
                return_code=return_code,
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated)

            if check and result.return_code != 0:
                raise SandboxCommandError(cmd=args, result=result)

            return result

    def add_files(
        self, *filenames: str,
        owner: str = SANDBOX_USERNAME,
        read_only: bool = False
    ) -> None:
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

    def _chown_files(self, filenames: Sequence[str]) -> None:
        chown_cmd = [
            'chown', '{}:{}'.format(SANDBOX_USERNAME, SANDBOX_USERNAME)]
        chown_cmd += filenames
        self.run_command(chown_cmd, as_root=True)


# A convenience function that calls subprocess.run with the given timeout,
# checks the return code (by passing check=True), and captures the output.
# If the command fails, logs error_msg_prefix and the stdout and stderr
# of the command.
def _subprocess_helper(
    cmd: List[str], *, timeout: Optional[int], error_msg_prefix: str,
    reraise_as: Optional[Type[Exception]] = None
) -> 'subprocess.CompletedProcess[str]':
    try:
        return subprocess.run(
            cmd,
            timeout=timeout,
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='surrogateescape'
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        if e.stdout is None:
            stdout = ''
        elif isinstance(e.stdout, bytes):
            stdout = e.stdout.decode(errors="surrogateescape")
        else:
            stdout = e.stdout

        if e.stderr is None:
            stderr = ''
        elif isinstance(e.stderr, bytes):
            stderr = e.stderr.decode(errors="surrogateescape")
        else:
            stderr = e.stderr

        error_msg = (
            error_msg_prefix + '\n'
            + str(e) + '\n'
            + f'Stdout:\n{stdout}\n'
            + f'Stderr:\n{stderr}\n'
        )

        logger.debug(error_msg)
        if reraise_as is not None:
            raise reraise_as(error_msg) from e
        else:
            raise


# Generator that reads amount_to_read bytes from file_obj, yielding
# one chunk at a time.
def _chunked_read(
    file_obj: IO[bytes],
    amount_to_read: int,
    chunk_size: int = 1024 * 16
) -> Iterator[bytes]:
    num_reads = amount_to_read // chunk_size
    for i in range(num_reads):
        yield file_obj.read(chunk_size)

    remainder = amount_to_read % chunk_size
    if remainder:
        yield file_obj.read(remainder)


def _mocking_hook(context: str = '', **kwargs: Any) -> None:
    """
    USE SPARINGLY

    Used to more easily insert side-effects at specific points in the program.
    Tests should patch this method with something that can perform the
    correct action needed for the test.

    The "context" argument is so that tests can perform different actions
    based on its value.

    The extra kwargs can be used to check hard-to-test internal values
    (like the fallback timeout, for example).
    """
    pass
