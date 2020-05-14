import io
import os
import unittest
from unittest import mock
import subprocess
import tempfile
import multiprocessing
import itertools
import time
import uuid
from typing import IO, Callable, TypeVar, Optional

from collections import OrderedDict

from .autograder_sandbox import (
    AutograderSandbox,
    SandboxCommandError,
    SANDBOX_USERNAME,
    SANDBOX_HOME_DIR_NAME,
    SANDBOX_DOCKER_IMAGE,
    CompletedCommand
)

from .output_size_performance_test import output_size_performance_test


def kb_to_bytes(num_kb: int) -> int:
    return 1000 * num_kb


def mb_to_bytes(num_mb: int) -> int:
    return 1000 * kb_to_bytes(num_mb)


def gb_to_bytes(num_gb: int) -> int:
    return 1000 * mb_to_bytes(num_gb)


class AutograderSandboxInitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.name = 'awexome_container{}'.format(uuid.uuid4().hex)
        self.environment_variables = OrderedDict(
            {'spam': 'egg', 'sausage': '42'})

    def test_default_init(self) -> None:
        sandbox = AutograderSandbox()
        self.assertIsNotNone(sandbox.name)
        self.assertFalse(sandbox.allow_network_access)
        self.assertEqual({}, sandbox.environment_variables)
        self.assertEqual('jameslp/ag-ubuntu-16:latest', sandbox.docker_image)

    def test_non_default_init(self) -> None:
        docker_image = 'waaaaluigi'
        sandbox = AutograderSandbox(
            name=self.name,
            docker_image=docker_image,
            allow_network_access=True,
            environment_variables=self.environment_variables
        )
        self.assertEqual(self.name, sandbox.name)
        self.assertEqual(docker_image, sandbox.docker_image)
        self.assertTrue(sandbox.allow_network_access)
        self.assertEqual(self.environment_variables, sandbox.environment_variables)


class AutograderSandboxBasicRunCommandTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.sandbox = AutograderSandbox()

        self.root_cmd = ["touch", "/"]

    def test_run_legal_command_non_root(self) -> None:
        stdout_content = "hello world"
        expected_output = stdout_content.encode() + b'\n'
        with self.sandbox:
            cmd_result = self.sandbox.run_command(["echo", stdout_content])
            self.assertEqual(0, cmd_result.return_code)
            self.assertEqual(expected_output, cmd_result.stdout.read())

    def test_run_illegal_command_non_root(self) -> None:
        with self.sandbox:
            cmd_result = self.sandbox.run_command(self.root_cmd)
            self.assertNotEqual(0, cmd_result.return_code)
            self.assertNotEqual("", cmd_result.stderr)

    def test_run_command_as_root(self) -> None:
        with self.sandbox:
            cmd_result = self.sandbox.run_command(self.root_cmd, as_root=True)
            self.assertEqual(0, cmd_result.return_code)
            self.assertEqual(b"", cmd_result.stderr.read())

    def test_run_command_raise_on_error(self) -> None:
        """
        Tests that an exception is thrown only when check is True
        and the command exits with nonzero status.
        """
        with self.sandbox:
            # No exception should be raised.
            cmd_result = self.sandbox.run_command(self.root_cmd, as_root=True, check=True)
            self.assertEqual(0, cmd_result.return_code)

            with self.assertRaises(SandboxCommandError):
                self.sandbox.run_command(self.root_cmd, check=True)

    def test_run_command_executable_does_not_exist_no_error(self) -> None:
        with self.sandbox:
            cmd_result = self.sandbox.run_command(['not_an_exe'])
            self.assertNotEqual(0, cmd_result.return_code)


class AutograderSandboxMiscTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.name = 'awexome_container{}'.format(uuid.uuid4().hex)
        self.environment_variables = OrderedDict(
            {'spam': 'egg', 'sausage': '42'})

        self.stdin = tempfile.NamedTemporaryFile()
        self.stdout = tempfile.NamedTemporaryFile()
        self.stderr = tempfile.NamedTemporaryFile()

    def tearDown(self) -> None:
        self.stdin.close()
        self.stdout.close()
        self.stderr.close()

    def _write_and_seek(self, file_obj: IO[bytes], content: bytes) -> None:
        file_obj.write(content)
        file_obj.seek(0)

    def test_very_large_io_no_truncate(self) -> None:
        output_size_performance_test(10 ** 9)

    def test_truncate_very_large_io(self) -> None:
        output_size_performance_test(10 ** 9, truncate=10**7)

    def test_truncate_stdout(self) -> None:
        truncate_length = 9
        long_output = b'a' * 100
        expected_output = long_output[:truncate_length]
        self._write_and_seek(self.stdin, long_output)
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(
                ['cat'], stdin=self.stdin, truncate_stdout=truncate_length)
            self.assertEqual(expected_output, result.stdout.read())
            self.assertTrue(result.stdout_truncated)
            self.assertFalse(result.stderr_truncated)

    def test_truncate_stderr(self) -> None:
        truncate_length = 13
        long_output = b'a' * 100
        expected_output = long_output[:truncate_length]
        self._write_and_seek(self.stdin, long_output)
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(
                ['bash', '-c', '>&2 cat'], stdin=self.stdin, truncate_stderr=truncate_length)
            self.assertEqual(expected_output, result.stderr.read())
            self.assertTrue(result.stderr_truncated)
            self.assertFalse(result.stdout_truncated)

    def test_run_command_with_input(self) -> None:
        expected_stdout = b'spam egg sausage spam'
        self._write_and_seek(self.stdin, expected_stdout)
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(['cat'], stdin=self.stdin)
            self.assertEqual(expected_stdout, result.stdout.read())

    def test_command_tries_to_read_from_stdin_when_stdin_arg_is_none(self) -> None:
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(
                ['python3', '-c', "import sys; sys.stdin.read(); print('done')"],
                max_stack_size=10000000,
                max_virtual_memory=500000000,
                timeout=2,
            )
            self.assertFalse(result.timed_out)
            self.assertEqual(0, result.return_code)

    def test_return_code_reported_and_stderr_recorded(self) -> None:
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(['ls', 'definitely not a file'])
            self.assertNotEqual(0, result.return_code)
            self.assertNotEqual('', result.stderr)

    def test_context_manager(self) -> None:
        with AutograderSandbox(name=self.name) as sandbox:
            self.assertEqual(self.name, sandbox.name)
            # If the container was created successfully, we
            # should get an error if we try to create another
            # container with the same name.
            with self.assertRaises(subprocess.CalledProcessError):
                with AutograderSandbox(name=self.name):
                    pass

        # The container should have been deleted at this point,
        # so we should be able to create another with the same name.
        with AutograderSandbox(name=self.name):
            pass

    def test_sandbox_environment_variables_set(self) -> None:
        print_env_var_script = "echo ${}".format(
            ' $'.join(self.environment_variables))

        sandbox = AutograderSandbox(
            environment_variables=self.environment_variables)
        with sandbox, tempfile.NamedTemporaryFile('w+') as f:
            f.write(print_env_var_script)
            f.seek(0)
            sandbox.add_files(f.name)
            result = sandbox.run_command(['bash', os.path.basename(f.name)])
            expected_output = ' '.join(
                str(val) for val in self.environment_variables.values())
            expected_output += '\n'
            self.assertEqual(expected_output, result.stdout.read().decode())

    def test_home_env_var_set_in_preexec(self) -> None:
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(['bash', '-c', 'printf $HOME'])
            self.assertEqual(SANDBOX_HOME_DIR_NAME, result.stdout.read().decode())

            result = sandbox.run_command(['bash', '-c', 'printf $USER'])
            self.assertEqual(SANDBOX_USERNAME, result.stdout.read().decode())

            result = sandbox.run_command(['bash', '-c', 'printf $HOME'], as_root=True)
            self.assertEqual('/root', result.stdout.read().decode())

    def test_reset(self) -> None:
        with AutograderSandbox() as sandbox:
            file_to_add = os.path.abspath(__file__)
            sandbox.add_files(file_to_add)

            ls_result = sandbox.run_command(['ls']).stdout
            self.assertEqual(os.path.basename(file_to_add) + '\n', ls_result.read().decode())

            sandbox.reset()
            self.assertEqual('', sandbox.run_command(['ls']).stdout.read().decode())

    def test_restart_added_files_preserved(self) -> None:
        with AutograderSandbox() as sandbox:
            file_to_add = os.path.abspath(__file__)
            sandbox.add_files(file_to_add)

            ls_result = sandbox.run_command(['ls']).stdout.read().decode()
            print(ls_result)
            self.assertEqual(os.path.basename(file_to_add) + '\n', ls_result)

            sandbox.restart()

            ls_result = sandbox.run_command(['ls']).stdout.read().decode()
            self.assertEqual(os.path.basename(file_to_add) + '\n', ls_result)

    def test_entire_process_tree_killed_on_timeout(self) -> None:
        for program_str in _PROG_WITH_SUBPROCESS_STALL, _PROG_WITH_PARENT_PROC_STALL:
            with AutograderSandbox() as sandbox:
                ps_result = sandbox.run_command(['ps', '-aux']).stdout.read().decode()
                print(ps_result)
                num_ps_lines = len(ps_result.split('\n'))
                print(num_ps_lines)

                script_file = _add_string_to_sandbox_as_file(
                    program_str, '.py', sandbox)

                start_time = time.time()
                result = sandbox.run_command(['python3', script_file], timeout=1)
                self.assertTrue(result.timed_out)

                time_elapsed = time.time() - start_time
                self.assertLess(time_elapsed, _SLEEP_TIME // 2,
                                msg='Killing processes took too long')

                ps_result_after_cmd = sandbox.run_command(
                    ['ps', '-aux']).stdout.read().decode()
                print(ps_result_after_cmd)
                num_ps_lines_after_cmd = len(ps_result_after_cmd.split('\n'))
                self.assertEqual(num_ps_lines, num_ps_lines_after_cmd)

    def test_command_can_leave_child_process_running(self) -> None:
        with AutograderSandbox() as sandbox:
            ps_result = sandbox.run_command(['ps', '-aux']).stdout.read().decode()
            print(ps_result)
            num_ps_lines = len(ps_result.split('\n'))
            print(num_ps_lines)

            script_file = _add_string_to_sandbox_as_file(_PROG_THAT_FORKS, '.py', sandbox)

            result = sandbox.run_command(['python3', script_file], timeout=1)
            self.assertFalse(result.timed_out)

            ps_result_after_cmd = sandbox.run_command(['ps', '-aux']).stdout.read().decode()
            print(ps_result_after_cmd)
            num_ps_lines_after_cmd = len(ps_result_after_cmd.split('\n'))
            self.assertEqual(num_ps_lines + 1, num_ps_lines_after_cmd)

    def test_try_to_change_cmd_runner(self) -> None:
        runner_path = '/usr/local/bin/cmd_runner.py'
        with AutograderSandbox() as sandbox:
            # Make sure the file path above is correct
            sandbox.run_command(['cat', runner_path], check=True)
            with self.assertRaises(SandboxCommandError):
                sandbox.run_command(['touch', runner_path], check=True)

    @mock.patch('subprocess.run')
    @mock.patch('subprocess.check_call')
    def test_container_create_timeout(self, mock_check_call: mock.Mock, *args: object) -> None:
        with AutograderSandbox(debug=True):
            args, kwargs = mock_check_call.call_args
            self.assertIsNone(kwargs['timeout'])

        timeout = 42
        with AutograderSandbox(container_create_timeout=timeout):
            args, kwargs = mock_check_call.call_args
            self.assertEqual(timeout, kwargs['timeout'])


class AutograderSandboxEncodeDecodeIOTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.non_utf = b'\x80 and some other stuff just because\n'
        with self.assertRaises(UnicodeDecodeError):
            self.non_utf.decode()
        self.file_to_print = 'non-utf.txt'
        with open(self.file_to_print, 'wb') as f:
            f.write(self.non_utf)

    def tearDown(self) -> None:
        os.remove(self.file_to_print)

    def test_non_unicode_chars_in_normal_output(self) -> None:
        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            result = sandbox.run_command(['cat', self.file_to_print])
            stdout = result.stdout.read()
            print(stdout)
            self.assertEqual(self.non_utf, stdout)

            result = sandbox.run_command(['bash', '-c', '>&2 cat ' + self.file_to_print])
            stderr = result.stderr.read()
            print(stderr)
            self.assertEqual(self.non_utf, stderr)

    def test_non_unicode_chars_in_output_command_timed_out(self) -> None:
        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            result = sandbox.run_command(
                ['bash', '-c', 'cat {}; sleep 5'.format(self.file_to_print)],
                timeout=1)
            self.assertTrue(result.timed_out)
            self.assertEqual(self.non_utf, result.stdout.read())

        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            result = sandbox.run_command(
                ['bash', '-c', '>&2 cat {}; sleep 5'.format(self.file_to_print)],
                timeout=1)
            self.assertTrue(result.timed_out)
            self.assertEqual(self.non_utf, result.stderr.read())

    def test_non_unicode_chars_in_output_on_process_error(self) -> None:
        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            with self.assertRaises(SandboxCommandError) as cm:
                sandbox.run_command(
                    ['bash', '-c', 'cat {}; exit 1'.format(self.file_to_print)],
                    check=True)
            self.assertIn(self.non_utf.decode('utf-8', 'surrogateescape'), str(cm.exception))

        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            with self.assertRaises(SandboxCommandError) as cm:
                sandbox.run_command(
                    ['bash', '-c', '>&2 cat {}; exit 1'.format(self.file_to_print)],
                    check=True)
            self.assertIn(self.non_utf.decode('utf-8', 'surrogateescape'), str(cm.exception))


_SLEEP_TIME = 6

_PROG_THAT_FORKS = """
import subprocess

print('hello', flush=True)
subprocess.Popen(['sleep', '{}'])
print('goodbye', flush=True)
""".format(_SLEEP_TIME)

_PROG_WITH_SUBPROCESS_STALL = """
import subprocess

print('hello', flush=True)
subprocess.call(['sleep', '{}'])
print('goodbye', flush=True)
""".format(_SLEEP_TIME)

_PROG_WITH_PARENT_PROC_STALL = """
import subprocess
import time

print('hello', flush=True)
subprocess.Popen(['sleep', '{}'])
time.sleep({})
print('goodbye', flush=True)
""".format(_SLEEP_TIME * 2, _SLEEP_TIME)


class AutograderSandboxResourceLimitTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.sandbox = AutograderSandbox()

        self.small_virtual_mem_limit = mb_to_bytes(100)
        self.large_virtual_mem_limit = gb_to_bytes(1)

    def test_run_command_timeout_exceeded(self) -> None:
        with self.sandbox:
            result = self.sandbox.run_command(["sleep", "10"], timeout=1)
            self.assertTrue(result.timed_out)

    def test_block_process_spawn(self) -> None:
        cmd = ['bash', '-c', 'echo spam | cat > egg.txt']
        with self.sandbox:
            # Spawning processes is allowed by default
            filename = _add_string_to_sandbox_as_file(
                _PROCESS_SPAWN_PROG_TMPL.format(num_processes=12, sleep_time=3), '.py',
                self.sandbox
            )
            result = self.sandbox.run_command(['python3', filename])
            self.assertEqual(0, result.return_code)

            result = self.sandbox.run_command(['python3', filename], block_process_spawn=True)
            stdout = result.stdout.read().decode()
            print(stdout)
            stderr = result.stderr.read().decode()
            print(stderr)
            self.assertNotEqual(0, result.return_code)
            self.assertIn('BlockingIOError', stderr)
            self.assertIn('Resource temporarily unavailable', stderr)

    def test_command_exceeds_stack_size_limit(self) -> None:
        stack_size_limit = mb_to_bytes(5)
        mem_to_use = stack_size_limit * 2
        with self.sandbox:
            self._do_stack_resource_limit_test(
                mem_to_use, stack_size_limit, self.sandbox)

    def test_command_doesnt_exceed_stack_size_limit(self) -> None:
        stack_size_limit = mb_to_bytes(30)
        mem_to_use = stack_size_limit // 2
        with self.sandbox:
            self._do_stack_resource_limit_test(
                mem_to_use, stack_size_limit, self.sandbox)

    def test_command_exceeds_virtual_mem_limit(self) -> None:
        virtual_mem_limit = mb_to_bytes(100)
        mem_to_use = virtual_mem_limit * 2
        with self.sandbox:
            self._do_heap_resource_limit_test(
                mem_to_use, virtual_mem_limit, self.sandbox)

    def test_command_doesnt_exceed_virtual_mem_limit(self) -> None:
        virtual_mem_limit = mb_to_bytes(100)
        mem_to_use = virtual_mem_limit // 2
        with self.sandbox:
            self._do_heap_resource_limit_test(
                mem_to_use, virtual_mem_limit, self.sandbox)

    def test_run_subsequent_commands_with_different_resource_limits(self) -> None:
        with self.sandbox:
            # Under limit
            self._do_stack_resource_limit_test(
                mb_to_bytes(1), mb_to_bytes(10), self.sandbox)
            # Over previous limit
            self._do_stack_resource_limit_test(
                mb_to_bytes(20), mb_to_bytes(10), self.sandbox)
            # Limit raised
            self._do_stack_resource_limit_test(
                mb_to_bytes(20), mb_to_bytes(50), self.sandbox)
            # Over new limit
            self._do_stack_resource_limit_test(
                mb_to_bytes(40), mb_to_bytes(30), self.sandbox)

            # Under limit
            self._do_heap_resource_limit_test(
                mb_to_bytes(10), mb_to_bytes(100), self.sandbox)
            # Over previous limit
            self._do_heap_resource_limit_test(
                mb_to_bytes(200), mb_to_bytes(100), self.sandbox)
            # Limit raised
            self._do_heap_resource_limit_test(
                mb_to_bytes(200), mb_to_bytes(300), self.sandbox)
            # Over new limit
            self._do_heap_resource_limit_test(
                mb_to_bytes(250), mb_to_bytes(200), self.sandbox)

    def _do_stack_resource_limit_test(
        self, mem_to_use: int, mem_limit: int, sandbox: AutograderSandbox
    ) -> None:
        prog_ret_code = _run_stack_usage_prog(mem_to_use, mem_limit, sandbox)

        self._check_resource_limit_test_result(
            prog_ret_code, mem_to_use, mem_limit)

    def _do_heap_resource_limit_test(
        self, mem_to_use: int, mem_limit: int, sandbox: AutograderSandbox
    ) -> None:
        prog_ret_code = _run_heap_usage_prog(mem_to_use, mem_limit, sandbox)
        self._check_resource_limit_test_result(
            prog_ret_code, mem_to_use, mem_limit)

    def _check_resource_limit_test_result(
        self, ret_code: Optional[int], resource_used: int, resource_limit: int
    ) -> None:
        if resource_used > resource_limit:
            self.assertNotEqual(0, ret_code)
        else:
            self.assertEqual(0, ret_code)

    def test_multiple_containers_dont_exceed_ulimits(self) -> None:
        """
        This is a sanity check to make sure that ulimits placed on
        different containers with the same UID don't conflict. All
        ulimits except for nproc are supposed to be process-linked
        rather than UID-linked.
        """
        self._do_parallel_container_stack_limit_test(
            16, mb_to_bytes(20), mb_to_bytes(30))

        self._do_parallel_container_heap_limit_test(
            16, mb_to_bytes(300), mb_to_bytes(500))

    def _do_parallel_container_stack_limit_test(
        self, num_containers: int, mem_to_use: int, mem_limit: int
    ) -> None:
        self._do_parallel_container_resource_limit_test(
            _run_stack_usage_prog, num_containers, mem_to_use, mem_limit)

    def _do_parallel_container_heap_limit_test(
        self, num_containers: int, mem_to_use: int, mem_limit: int
    ) -> None:
        self._do_parallel_container_resource_limit_test(
            _run_heap_usage_prog, num_containers, mem_to_use, mem_limit)

    def _do_parallel_container_resource_limit_test(
        self, func_to_run: Callable[[int, int, AutograderSandbox], Optional[int]],
        num_containers: int,
        amount_to_use: int,
        resource_limit: int
    ) -> None:
        with multiprocessing.Pool(processes=num_containers) as p:
            return_codes = p.starmap(
                func_to_run,
                itertools.repeat((amount_to_use, resource_limit, None),
                                 num_containers))

        print(return_codes)
        for ret_code in return_codes:
            self.assertEqual(0, ret_code)


def _run_stack_usage_prog(
    mem_to_use: int, mem_limit: int, sandbox: AutograderSandbox
) -> Optional[int]:
    def _run_prog(sandbox: AutograderSandbox) -> Optional[int]:
        prog = _STACK_USAGE_PROG_TMPL.format(num_bytes_on_stack=mem_to_use)
        filename = _add_string_to_sandbox_as_file(prog, '.cpp', sandbox)
        exe_name = _compile_in_sandbox(sandbox, filename)
        result = sandbox.run_command(
            ['./' + exe_name], max_stack_size=mem_limit)
        return result.return_code

    return _call_function_and_allocate_sandbox_if_needed(_run_prog, sandbox)


_STACK_USAGE_PROG_TMPL = """#include <iostream>
#include <thread>
#include <cstring>

using namespace std;

int main() {{
    char stacky[{num_bytes_on_stack}];
    for (int i = 0; i < {num_bytes_on_stack} - 1; ++i) {{
        stacky[i] = 'a';
    }}
    stacky[{num_bytes_on_stack} - 1] = '\\0';

    cout << "Sleeping" << endl;
    this_thread::sleep_for(chrono::seconds(2));

    cout << "Allocated " << strlen(stacky) + 1 << " bytes" << endl;

    return 0;
}}
"""


def _run_heap_usage_prog(
    mem_to_use: int, mem_limit: int, sandbox: AutograderSandbox
) -> Optional[int]:
    def _run_prog(sandbox: AutograderSandbox) -> Optional[int]:
        prog = _HEAP_USAGE_PROG_TMPL.format(num_bytes_on_heap=mem_to_use, sleep_time=2)
        filename = _add_string_to_sandbox_as_file(prog, '.cpp', sandbox)
        exe_name = _compile_in_sandbox(sandbox, filename)
        result = result = sandbox.run_command(
            ['./' + exe_name], max_virtual_memory=mem_limit)

        return result.return_code

    return _call_function_and_allocate_sandbox_if_needed(_run_prog, sandbox)


_HEAP_USAGE_PROG_TMPL = """#include <iostream>
#include <thread>
#include <cstring>

using namespace std;

const size_t num_bytes_on_heap = {num_bytes_on_heap};

int main() {{
    cout << "Allocating an array of " << num_bytes_on_heap << " bytes" << endl;
    char* heapy = new char[num_bytes_on_heap];
    for (size_t i = 0; i < num_bytes_on_heap - 1; ++i) {{
        heapy[i] = 'a';
    }}
    heapy[num_bytes_on_heap - 1] = '\\0';

    cout << "Sleeping" << endl;
    this_thread::sleep_for(chrono::seconds({sleep_time}));

    cout << "Allocated and filled " << strlen(heapy) + 1 << " bytes" << endl;
    return 0;
}}
"""


def _compile_in_sandbox(sandbox: AutograderSandbox, *files_to_compile: str) -> str:
    exe_name = 'prog'
    sandbox.run_command(
        ['g++', '--std=c++11', '-Wall', '-Werror'] + list(files_to_compile)
        + ['-o', exe_name], check=True)
    return exe_name


_PROCESS_SPAWN_PROG_TMPL = """
import time
import subprocess


processes = []
for i in range({num_processes}):
    proc = subprocess.Popen(['sleep', '{sleep_time}'])
    processes.append(proc)

time.sleep({sleep_time})

for proc in processes:
    proc.communicate()
"""


def _add_string_to_sandbox_as_file(
    string: str, file_extension: str, sandbox: AutograderSandbox
) -> str:
    with tempfile.NamedTemporaryFile('w+', suffix=file_extension) as f:
        f.write(string)
        f.seek(0)
        sandbox.add_files(f.name)

        return os.path.basename(f.name)


ReturnType = TypeVar('ReturnType')


def _call_function_and_allocate_sandbox_if_needed(
    func: Callable[[AutograderSandbox], ReturnType], sandbox: Optional[AutograderSandbox]
) -> ReturnType:
    if sandbox is None:
        sandbox = AutograderSandbox()
        with sandbox:
            return func(sandbox)
    else:
        return func(sandbox)

# -----------------------------------------------------------------------------


class ContainerLevelResourceLimitTestCase(unittest.TestCase):
    def test_pid_limit(self) -> None:
        with AutograderSandbox() as sandbox:
            filename = _add_string_to_sandbox_as_file(
                _PROCESS_SPAWN_PROG_TMPL.format(num_processes=1000, sleep_time=5), '.py', sandbox
            )

            # The limit should apply to all users, root or otherwise
            result = sandbox.run_command(['python3', filename], as_root=True)
            stdout = result.stdout.read().decode()
            print(stdout)
            stderr = result.stderr.read().decode()
            print(stderr)
            self.assertNotEqual(0, result.return_code)
            self.assertIn('BlockingIOError', stderr)
            self.assertIn('Resource temporarily unavailable', stderr)

    def test_processes_created_and_finish_then_more_processes_spawned(self) -> None:
        spawn_twice_prog = """
import time
import subprocess


for i in range(2):
    processes = []
    print('spawing processes')
    for i in range({num_processes}):
        proc = subprocess.Popen(['sleep', '{sleep_time}'])
        processes.append(proc)

    time.sleep({sleep_time})

    print('waiting for processes to finish')
    for proc in processes:
        proc.communicate()
"""
        with AutograderSandbox() as sandbox:
            filename = _add_string_to_sandbox_as_file(
                spawn_twice_prog.format(num_processes=350, sleep_time=5), '.py', sandbox
            )

            result = sandbox.run_command(['python3', filename])
            print(result.stdout.read().decode())
            print(result.stderr.read().decode())
            self.assertEqual(0, result.return_code)

    def test_fallback_time_limit_is_twice_timeout(self) -> None:
        with AutograderSandbox(min_fallback_timeout=4) as sandbox:
            to_throw = subprocess.TimeoutExpired([], 10)
            subprocess_run_mock = mock.Mock(side_effect=to_throw)
            with mock.patch('subprocess.run', new=subprocess_run_mock):
                result = sandbox.run_command(['sleep', '20'], timeout=5)
                stdout = result.stdout.read().decode()
                stderr = result.stderr.read().decode()
                print(stdout)
                print(stderr)

                args, kwargs = subprocess_run_mock.call_args
                self.assertEqual(10, kwargs['timeout'])

                self.assertTrue(result.timed_out)
                self.assertIsNone(result.return_code)
                self.assertIn('fallback timeout', stderr)

    def test_fallback_time_limit_is_min_fallback_timeout(self) -> None:
        with AutograderSandbox(min_fallback_timeout=60) as sandbox:
            to_throw = subprocess.TimeoutExpired([], 60)
            subprocess_run_mock = mock.Mock(side_effect=to_throw)
            with mock.patch('subprocess.run', new=subprocess_run_mock):
                result = sandbox.run_command(['sleep', '20'], timeout=10)
                stdout = result.stdout.read().decode()
                stderr = result.stderr.read().decode()

                args, kwargs = subprocess_run_mock.call_args
                self.assertEqual(60, kwargs['timeout'])

                self.assertTrue(result.timed_out)
                self.assertIsNone(result.return_code)
                self.assertIn('fallback timeout', stderr)

    # Since we disable the OOM killer for the container, we expect
    # commands to time out while waiting for memory to be paged
    # in and out.
    def test_memory_limit_no_oom_kill(self) -> None:
        program_str = _HEAP_USAGE_PROG_TMPL.format(num_bytes_on_heap=4 * 10 ** 9, sleep_time=0)
        with AutograderSandbox(memory_limit='2g') as sandbox:
            filename = _add_string_to_sandbox_as_file(program_str, '.cpp', sandbox)
            exe_name = _compile_in_sandbox(sandbox, filename)
            # The limit should apply to all users, root or otherwise
            result = sandbox.run_command(['./' + exe_name], timeout=20, as_root=True)

            print(result.return_code)
            print(result.stdout.read().decode())
            print(result.stderr.read().decode())
            self.assertTrue(result.timed_out)

# -----------------------------------------------------------------------------


_GOOGLE_IP_ADDR = "216.58.214.196"


class AutograderSandboxNetworkAccessTestCase(unittest.TestCase):

    def setUp(self) -> None:
        super().setUp()

        self.google_ping_cmd = ['ping', '-c', '5', _GOOGLE_IP_ADDR]

    def test_networking_disabled(self) -> None:
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.return_code)

    def test_networking_enabled(self) -> None:
        with AutograderSandbox(allow_network_access=True) as sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertEqual(0, result.return_code)

    def test_set_allow_network_access(self) -> None:
        sandbox = AutograderSandbox()
        self.assertFalse(sandbox.allow_network_access)
        with sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.return_code)

        sandbox.allow_network_access = True
        self.assertTrue(sandbox.allow_network_access)
        with sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertEqual(0, result.return_code)

        sandbox.allow_network_access = False
        self.assertFalse(sandbox.allow_network_access)
        with sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.return_code)

    def test_error_set_allow_network_access_while_running(self) -> None:
        with AutograderSandbox() as sandbox:
            with self.assertRaises(ValueError):
                sandbox.allow_network_access = True

            self.assertFalse(sandbox.allow_network_access)
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.return_code)


class AutograderSandboxCopyFilesTestCase(unittest.TestCase):

    def test_copy_files_into_sandbox(self) -> None:
        files = []
        try:
            for i in range(10):
                f = tempfile.NamedTemporaryFile(mode='w+')
                f.write('this is file {}'.format(i))
                f.seek(0)
                files.append(f)

            filenames = [file_.name for file_ in files]

            with AutograderSandbox() as sandbox:
                sandbox.add_files(*filenames)

                ls_result = sandbox.run_command(['ls']).stdout.read().decode()
                actual_filenames = [
                    filename.strip() for filename in ls_result.split()]
                expected_filenames = [
                    os.path.basename(filename) for filename in filenames]
                self.assertCountEqual(expected_filenames, actual_filenames)

                for file_ in files:
                    file_.seek(0)
                    expected_content = file_.read()
                    actual_content = sandbox.run_command(
                        ['cat', os.path.basename(file_.name)]
                    ).stdout.read().decode()
                    self.assertEqual(expected_content, actual_content)
        finally:
            for file_ in files:
                file_.close()

    def test_copy_and_rename_file_into_sandbox(self) -> None:
        expected_content = 'this is a file'
        with tempfile.NamedTemporaryFile('w+') as f:
            f.write(expected_content)
            f.seek(0)

            with AutograderSandbox() as sandbox:
                new_name = 'new_filename.txt'
                sandbox.add_and_rename_file(f.name, new_name)

                ls_result = sandbox.run_command(['ls']).stdout.read().decode()
                actual_filenames = [filename.strip() for filename in ls_result.split()]
                expected_filenames = [new_name]
                self.assertCountEqual(expected_filenames, actual_filenames)

                actual_content = sandbox.run_command(['cat', new_name]).stdout.read().decode()
                self.assertEqual(expected_content, actual_content)

    def test_add_files_root_owner_and_read_only(self) -> None:
        original_content = "some stuff you shouldn't change"
        overwrite_content = 'lol I changed it anyway u nub'
        with tempfile.NamedTemporaryFile('w+') as f:
            f.write(original_content)
            f.seek(0)

            added_filename = os.path.basename(f.name)

            with AutograderSandbox() as sandbox:
                sandbox.add_files(f.name, owner='root', read_only=True)

                actual_content = sandbox.run_command(
                    ['cat', added_filename], check=True
                ).stdout.read().decode()
                self.assertEqual(original_content, actual_content)

                with self.assertRaises(SandboxCommandError):
                    sandbox.run_command(['touch', added_filename], check=True)

                with self.assertRaises(SandboxCommandError):
                    sandbox.run_command(
                        ['bash', '-c',
                         "printf '{}' > {}".format(overwrite_content, added_filename)],
                        check=True)

                actual_content = sandbox.run_command(
                    ['cat', added_filename], check=True
                ).stdout.read().decode()
                self.assertEqual(original_content, actual_content)

                root_touch_result = sandbox.run_command(
                    ['touch', added_filename], check=True, as_root=True)
                self.assertEqual(0, root_touch_result.return_code)

                sandbox.run_command(
                    ['bash', '-c', "printf '{}' > {}".format(overwrite_content, added_filename)],
                    as_root=True, check=True)
                actual_content = sandbox.run_command(
                    ['cat', added_filename]
                ).stdout.read().decode()
                self.assertEqual(overwrite_content, actual_content)

    def test_overwrite_non_read_only_file(self) -> None:
        original_content = "some stuff"
        overwrite_content = 'some new stuff'
        with tempfile.NamedTemporaryFile('w+') as f:
            f.write(original_content)
            f.seek(0)

            added_filename = os.path.basename(f.name)

            with AutograderSandbox() as sandbox:
                sandbox.add_files(f.name)

                actual_content = sandbox.run_command(
                    ['cat', added_filename], check=True
                ).stdout.read().decode()
                self.assertEqual(original_content, actual_content)

                sandbox.run_command(
                    ['bash', '-c', "printf '{}' > {}".format(overwrite_content, added_filename)])
                actual_content = sandbox.run_command(
                    ['cat', added_filename], check=True
                ).stdout.read().decode()
                self.assertEqual(overwrite_content, actual_content)

    def test_error_add_files_invalid_owner(self) -> None:
        with AutograderSandbox() as sandbox:
            with self.assertRaises(ValueError):
                sandbox.add_files('steve', owner='not_an_owner')


class OverrideCmdAndEntrypointTestCase(unittest.TestCase):
    def test_override_image_cmd(self) -> None:
        dockerfile = """FROM jameslp/autograder-sandbox:3.1.2
CMD ["echo", "goodbye"]
"""
        tag = 'sandbox_test_image_with_cmd'
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, 'Dockerfile'), 'w') as f:
                f.write(dockerfile)
            subprocess.run('docker build -t {} {}'.format(tag, temp_dir), check=True, shell=True)

        with AutograderSandbox(docker_image=tag) as sandbox:
            time.sleep(2)
            result = sandbox.run_command(['echo', 'hello'])
            self.assertEqual(0, result.return_code)
            self.assertEqual('hello\n', result.stdout.read().decode())

    def test_override_image_entrypoint(self) -> None:
        dockerfile = """FROM jameslp/autograder-sandbox:3.1.2
ENTRYPOINT ["echo", "goodbye"]
"""
        tag = 'sandbox_test_image_with_entrypoint'
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, 'Dockerfile'), 'w') as f:
                f.write(dockerfile)
            subprocess.run('docker build -t {} {}'.format(tag, temp_dir), check=True, shell=True)

        with AutograderSandbox(docker_image=tag) as sandbox:
            time.sleep(2)
            result = sandbox.run_command(['echo', 'hello'])
            self.assertEqual(0, result.return_code)
            self.assertEqual('hello\n', result.stdout.read().decode())

    def test_override_image_cmd_and_entrypoint(self) -> None:
        dockerfile = """FROM jameslp/autograder-sandbox:3.1.2
ENTRYPOINT ["echo", "goodbye"]
CMD ["echo", "goodbye"]
"""
        tag = 'sandbox_test_image_with_cmd_and_entrypoint'
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, 'Dockerfile'), 'w') as f:
                f.write(dockerfile)
            subprocess.run('docker build -t {} {}'.format(tag, temp_dir), check=True, shell=True)

        with AutograderSandbox(docker_image=tag) as sandbox:
            time.sleep(2)
            result = sandbox.run_command(['echo', 'hello'])
            self.assertEqual(0, result.return_code)
            self.assertEqual('hello\n', result.stdout.read().decode())


if __name__ == '__main__':
    unittest.main()
