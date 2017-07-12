import os
import unittest
from unittest import mock
import subprocess
import tempfile
import multiprocessing
import itertools
import time
import uuid
import typing

from collections import OrderedDict

from autograder_sandbox import AutograderSandbox, VERSION


def kb_to_bytes(num_kb):
    return 1000 * num_kb


def mb_to_bytes(num_mb):
    return 1000 * kb_to_bytes(num_mb)


def gb_to_bytes(num_gb):
    return 1000 * mb_to_bytes(num_gb)


class AutograderSandboxInitTestCase(unittest.TestCase):

    def setUp(self):
        self.name = 'awexome_container{}'.format(uuid.uuid4().hex)
        self.environment_variables = OrderedDict(
            {'spam': 'egg', 'sausage': 42})

    def test_default_init(self):
        sandbox = AutograderSandbox()
        self.assertIsNotNone(sandbox.name)
        self.assertFalse(sandbox.allow_network_access)
        self.assertEqual({}, sandbox.environment_variables)
        self.assertEqual('jameslp/autograder-sandbox:{}'.format(VERSION), sandbox.docker_image)

    def test_non_default_init(self):
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


class AutograderSandboxMiscTestCase(unittest.TestCase):

    def setUp(self):
        self.name = 'awexome_container{}'.format(uuid.uuid4().hex)
        self.environment_variables = OrderedDict(
            {'spam': 'egg', 'sausage': 42})

    def test_run_command_with_input(self):
        input_content = 'spam egg sausage spam'
        with AutograderSandbox() as sandbox:  # type: AutograderSandbox
            result = sandbox.run_command(['cat'], input=input_content)
            self.assertEqual(input_content, result.stdout)

    def test_return_code_reported_and_stderr_recorded(self):
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(['ls', 'definitely not a file'])
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual('', result.stderr)

    def test_context_manager(self):
        with AutograderSandbox(name=self.name) as sandbox:  # type: AutograderSandbox
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

    def test_sandbox_environment_variables_set(self):
        print_env_var_script = "echo ${}".format(
            ' $'.join(self.environment_variables))

        sandbox = AutograderSandbox(
            environment_variables=self.environment_variables)
        with sandbox, typing.cast(typing.TextIO,
                                  tempfile.NamedTemporaryFile('w+')) as f:
            f.write(print_env_var_script)
            f.seek(0)
            sandbox.add_files(f.name)
            result = sandbox.run_command(['bash', os.path.basename(f.name)])
            expected_output = ' '.join(
                str(val) for val in self.environment_variables.values())
            expected_output += '\n'
            self.assertEqual(expected_output, result.stdout)

    def test_reset(self):
        with AutograderSandbox() as sandbox:
            file_to_add = os.path.abspath(__file__)
            sandbox.add_files(file_to_add)

            ls_result = sandbox.run_command(['ls']).stdout
            self.assertEqual(os.path.basename(file_to_add) + '\n', ls_result)

            sandbox.reset()

            ls_result = sandbox.run_command(['ls']).stdout
            self.assertEqual('', ls_result)

    def test_restart_added_files_preserved(self):
        with AutograderSandbox() as sandbox:
            file_to_add = os.path.abspath(__file__)
            sandbox.add_files(file_to_add)

            ls_result = sandbox.run_command(['ls']).stdout
            print(ls_result)
            self.assertEqual(os.path.basename(file_to_add) + '\n', ls_result)

            sandbox.restart()

            ls_result = sandbox.run_command(['ls']).stdout
            self.assertEqual(os.path.basename(file_to_add) + '\n', ls_result)

    def test_entire_process_tree_killed_on_timeout(self):
        for program_str in _PROG_THAT_FORKS, _PROG_WITH_SUBPROCESS_STALL:
            with AutograderSandbox() as sandbox:
                ps_result = sandbox.run_command(['ps', '-aux']).stdout
                print(ps_result)
                num_ps_lines = len(ps_result.split('\n'))
                print(num_ps_lines)

                script_file = _add_string_to_sandbox_as_file(
                    program_str, '.py', sandbox)

                start_time = time.time()
                with self.assertRaises(subprocess.TimeoutExpired):
                    sandbox.run_command(['python3', script_file], timeout=1)

                time_elapsed = time.time() - start_time
                self.assertLess(time_elapsed, _SLEEP_TIME // 2,
                                msg='Killing processes took too long')

                ps_result_after_restart = sandbox.run_command(
                    ['ps', '-aux']).stdout
                print(ps_result_after_restart)
                num_ps_lines_after_restart = len(
                    ps_result_after_restart.split('\n'))
                self.assertEqual(num_ps_lines, num_ps_lines_after_restart)

    def test_try_to_change_cmd_runner(self):
        runner_path = '/usr/local/bin/cmd_runner.py'
        with AutograderSandbox() as sandbox:  # type: AutograderSandbox
            # Make sure the file path above is correct
            sandbox.run_command(['cat', runner_path], check=True)
            with self.assertRaises(subprocess.CalledProcessError):
                sandbox.run_command(['touch', runner_path], check=True)

    @mock.patch('subprocess.run')
    @mock.patch('subprocess.check_call')
    def test_container_create_timeout(self, mock_check_call, *args):
        print(mock)
        with AutograderSandbox(debug=True):
            args, kwargs = mock_check_call.call_args
            self.assertIsNone(kwargs['timeout'])

        timeout = 42
        with AutograderSandbox(container_create_timeout=timeout):
            args, kwargs = mock_check_call.call_args
            self.assertEqual(timeout, kwargs['timeout'])


class AutograderSandboxEncodeDecodeIOTestCase(unittest.TestCase):
    def setUp(self):
        self.non_utf = b'\x80 and some other stuff just because\n'
        self.file_to_print = 'non-utf.txt'
        with open(self.file_to_print, 'wb') as f:
            f.write(self.non_utf)

        self.escaped_non_utf = self.non_utf.decode('utf-8', 'backslashreplace')

    def test_non_default_strict_encoding_errors_policy(self):
        expected_output = '\udc80 and some other stuff just because\n'
        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)
            result = sandbox.run_command(
                ['cat', self.file_to_print], errors='surrogateescape')
            self.assertEqual(expected_output, result.stdout)

    def test_non_unicode_chars_in_normal_output(self):
        with AutograderSandbox() as sandbox:  # type: AutograderSandbox
            sandbox.add_files(self.file_to_print)

            result = sandbox.run_command(['cat', self.file_to_print])
            print(result.stdout)
            self.assertEqual(self.escaped_non_utf, result.stdout)

            result = sandbox.run_command(['bash', '-c', '>&2 cat ' + self.file_to_print])
            print(result.stderr)
            self.assertEqual(self.escaped_non_utf, result.stderr)

    def test_output_encoded_on_timeout(self):
        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            with self.assertRaises(subprocess.TimeoutExpired) as cm:
                sandbox.run_command(
                    ['bash', '-c', 'cat {}; sleep 5'.format(self.file_to_print)],
                    timeout=1)
            self.assertEqual(self.escaped_non_utf, cm.exception.stdout)

        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            with self.assertRaises(subprocess.TimeoutExpired) as cm:
                sandbox.run_command(
                    ['bash', '-c', '>&2 cat {}; sleep 5'.format(self.file_to_print)],
                    timeout=1)
            self.assertEqual(self.escaped_non_utf, cm.exception.stderr)

    def test_output_encoded_on_process_error(self):
        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            with self.assertRaises(subprocess.CalledProcessError) as cm:
                sandbox.run_command(
                    ['bash', '-c', 'cat {}; exit 1'.format(self.file_to_print)],
                    check=True)
            self.assertEqual(self.escaped_non_utf, cm.exception.stdout)

        with AutograderSandbox() as sandbox:
            sandbox.add_files(self.file_to_print)

            with self.assertRaises(subprocess.CalledProcessError) as cm:
                sandbox.run_command(
                    ['bash', '-c', '>&2 cat {}; exit 1'.format(self.file_to_print)],
                    check=True)
            self.assertEqual(self.escaped_non_utf, cm.exception.stderr)


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


class AutograderSandboxBasicRunCommandTestCase(unittest.TestCase):

    def setUp(self):
        self.sandbox = AutograderSandbox()

        self.root_cmd = ["touch", "/"]

    def test_run_legal_command_non_root(self):
        stdout_content = "hello world"
        with self.sandbox:
            cmd_result = self.sandbox.run_command(["echo", stdout_content])
            self.assertEqual(0, cmd_result.returncode)
            self.assertEqual(stdout_content + '\n', cmd_result.stdout)

    def test_run_illegal_command_non_root(self):
        with self.sandbox:
            cmd_result = self.sandbox.run_command(self.root_cmd)
            self.assertNotEqual(0, cmd_result.returncode)
            self.assertNotEqual("", cmd_result.stderr)

    def test_run_command_as_root(self):
        with self.sandbox:
            cmd_result = self.sandbox.run_command(self.root_cmd, as_root=True)
            self.assertEqual(0, cmd_result.returncode)
            self.assertEqual("", cmd_result.stderr)

    def test_run_command_raise_on_error(self):
        """
        Tests that an exception is thrown only when check is True
        and the command exits with nonzero status.
        """
        with self.sandbox:
            # No exception should be raised.
            cmd_result = self.sandbox.run_command(
                self.root_cmd, as_root=True,
                check=True)  # type: subprocess.CompletedProcess
            self.assertEqual(0, cmd_result.returncode)

            with self.assertRaises(subprocess.CalledProcessError):
                self.sandbox.run_command(self.root_cmd, check=True)


class AutograderSandboxResourceLimitTestCase(unittest.TestCase):

    def setUp(self):
        self.sandbox = AutograderSandbox()

        self.small_virtual_mem_limit = mb_to_bytes(100)
        self.large_virtual_mem_limit = gb_to_bytes(1)

    def test_run_command_timeout_exceeded(self):
        with self.sandbox:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.sandbox.run_command(["sleep", "10"], timeout=1)

    def test_command_exceeds_process_limit(self):
        process_limit = 0
        processes_to_spawn = process_limit + 2

        with self.sandbox:
            self._do_process_resource_limit_test(
                processes_to_spawn, process_limit, self.sandbox)

    def test_command_doesnt_exceed_process_limit(self):
        process_limit = 10
        processes_to_spawn = process_limit - 2

        with self.sandbox:
            self._do_process_resource_limit_test(
                processes_to_spawn, process_limit, self.sandbox)

    def test_command_spawns_no_processes_with_limit_zero(self):
        with self.sandbox:
            self._do_process_resource_limit_test(0, 0, self.sandbox)

    def test_command_exceeds_stack_size_limit(self):
        stack_size_limit = mb_to_bytes(5)
        mem_to_use = stack_size_limit * 2
        with self.sandbox:
            self._do_stack_resource_limit_test(
                mem_to_use, stack_size_limit, self.sandbox)

    def test_command_doesnt_exceed_stack_size_limit(self):
        stack_size_limit = mb_to_bytes(30)
        mem_to_use = stack_size_limit // 2
        with self.sandbox:
            self._do_stack_resource_limit_test(
                mem_to_use, stack_size_limit, self.sandbox)

    def test_command_exceeds_virtual_mem_limit(self):
        virtual_mem_limit = mb_to_bytes(100)
        mem_to_use = virtual_mem_limit * 2
        with self.sandbox:
            self._do_heap_resource_limit_test(
                mem_to_use, virtual_mem_limit, self.sandbox)

    def test_command_doesnt_exceed_virtual_mem_limit(self):
        virtual_mem_limit = mb_to_bytes(100)
        mem_to_use = virtual_mem_limit // 2
        with self.sandbox:
            self._do_heap_resource_limit_test(
                mem_to_use, virtual_mem_limit, self.sandbox)

    def test_run_subsequent_commands_with_different_resource_limits(self):
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

            # Under limit
            self._do_process_resource_limit_test(0, 0, self.sandbox)
            # Over previous limit
            self._do_process_resource_limit_test(2, 0, self.sandbox)
            # Limit raised
            self._do_process_resource_limit_test(2, 5, self.sandbox)
            # Over new limit
            self._do_process_resource_limit_test(10, 7, self.sandbox)

    def _do_stack_resource_limit_test(self, mem_to_use, mem_limit, sandbox):
        prog_ret_code = _run_stack_usage_prog(mem_to_use, mem_limit, sandbox)

        self._check_resource_limit_test_result(
            prog_ret_code, mem_to_use, mem_limit)

    def _do_heap_resource_limit_test(self, mem_to_use, mem_limit, sandbox):
        prog_ret_code = _run_heap_usage_prog(mem_to_use, mem_limit, sandbox)
        self._check_resource_limit_test_result(
            prog_ret_code, mem_to_use, mem_limit)

    def _do_process_resource_limit_test(self, num_processes_to_spawn,
                                        process_limit, sandbox):
        prog_ret_code = _run_process_spawning_prog(
            num_processes_to_spawn, process_limit, sandbox)

        self._check_resource_limit_test_result(
            prog_ret_code, num_processes_to_spawn, process_limit)

    def _check_resource_limit_test_result(self, ret_code, resource_used,
                                          resource_limit):
        if resource_used > resource_limit:
            self.assertNotEqual(0, ret_code)
        else:
            self.assertEqual(0, ret_code)

    def test_multiple_containers_dont_exceed_ulimits(self):
        """
        One quirk of docker containers is that if there are multiple users
        created in different containers but with the same UID, the resource
        usage of all those users will contribute to hitting the same ulimits.
        This test makes sure that valid processes aren't randomly cut off.
        """
        self._do_parallel_container_stack_limit_test(
            16, mb_to_bytes(20), mb_to_bytes(30))

        self._do_parallel_container_heap_limit_test(
            16, mb_to_bytes(300), mb_to_bytes(500))

        self._do_parallel_container_process_limit_test(16, 3, 5)
        self._do_parallel_container_process_limit_test(15, 0, 0)

    def _do_parallel_container_stack_limit_test(self, num_containers,
                                                mem_to_use, mem_limit):
        self._do_parallel_container_resource_limit_test(
            _run_stack_usage_prog, num_containers, mem_to_use, mem_limit)

    def _do_parallel_container_heap_limit_test(self, num_containers,
                                               mem_to_use, mem_limit):
        self._do_parallel_container_resource_limit_test(
            _run_heap_usage_prog, num_containers, mem_to_use, mem_limit)

    def _do_parallel_container_process_limit_test(self, num_containers,
                                                  num_processes_to_spawn,
                                                  process_limit):
        self._do_parallel_container_resource_limit_test(
            _run_process_spawning_prog, num_containers,
            num_processes_to_spawn, process_limit)

    def _do_parallel_container_resource_limit_test(self, func_to_run,
                                                   num_containers,
                                                   amount_to_use,
                                                   resource_limit):
        with multiprocessing.Pool(processes=num_containers) as p:
            return_codes = p.starmap(
                func_to_run,
                itertools.repeat((amount_to_use, resource_limit, None),
                                 num_containers))

        print(return_codes)
        for ret_code in return_codes:
            self.assertEqual(0, ret_code)


def _run_stack_usage_prog(mem_to_use, mem_limit, sandbox):
    def _run_prog(sandbox):
        prog = _STACK_USAGE_PROG_TMPL.format(num_bytes_on_stack=mem_to_use)
        filename = _add_string_to_sandbox_as_file(prog, '.cpp', sandbox)
        exe_name = _compile_in_sandbox(sandbox, filename)
        result = sandbox.run_command(
            ['./' + exe_name], max_stack_size=mem_limit)
        return result.returncode

    return _call_function_and_allocate_sandbox_if_needed(_run_prog, sandbox)


_STACK_USAGE_PROG_TMPL = """#include <iostream>
#include <thread>

using namespace std;

int main()
{{
    char stacky[{num_bytes_on_stack}];

    this_thread::sleep_for(chrono::seconds(2));

    cout << stacky << endl;
    return 0;
}}
"""


def _run_heap_usage_prog(mem_to_use, mem_limit, sandbox):
    def _run_prog(sandbox):
        prog = _HEAP_USAGE_PROG_TMPL.format(num_bytes_on_heap=mem_to_use)
        filename = _add_string_to_sandbox_as_file(prog, '.cpp', sandbox)
        exe_name = _compile_in_sandbox(sandbox, filename)
        result = result = sandbox.run_command(
            ['./' + exe_name], max_virtual_memory=mem_limit)

        return result.returncode

    return _call_function_and_allocate_sandbox_if_needed(_run_prog, sandbox)


_HEAP_USAGE_PROG_TMPL = """#include <iostream>
#include <thread>

using namespace std;

int main()
{{
    char* heapy = new char[{num_bytes_on_heap}];

    this_thread::sleep_for(chrono::seconds(2));

    cout << heapy << endl;
    return 0;
}}
"""


def _compile_in_sandbox(sandbox, *files_to_compile):
    exe_name = 'prog'
    sandbox.run_command(
        ['g++', '--std=c++11'] + list(files_to_compile) +
        ['-o', exe_name], check=True)
    return exe_name


def _run_process_spawning_prog(num_processes_to_spawn, process_limit,
                               sandbox):
    def _run_prog(sandbox):
        prog = _PROCESS_SPAWN_PROG_TMPL.format(
            num_processes=num_processes_to_spawn)
        filename = _add_string_to_sandbox_as_file(prog, '.py', sandbox)

        result = sandbox.run_command(['python3', filename],
                                     max_num_processes=process_limit)
        return result.returncode

    return _call_function_and_allocate_sandbox_if_needed(_run_prog, sandbox)


_PROCESS_SPAWN_PROG_TMPL = """
import time
import subprocess


processes = []
for i in range({num_processes}):
    proc = subprocess.Popen(['sleep', '2'])
    processes.append(proc)

time.sleep(2)

for proc in processes:
    proc.communicate()
"""


def _add_string_to_sandbox_as_file(string, file_extension, sandbox):
    with tempfile.NamedTemporaryFile('w+', suffix=file_extension) as f:
        f.write(string)
        f.seek(0)
        sandbox.add_files(f.name)

        return os.path.basename(f.name)


def _call_function_and_allocate_sandbox_if_needed(func, sandbox):
    if sandbox is None:
        sandbox = AutograderSandbox()
        with sandbox:
            return func(sandbox)
    else:
        return func(sandbox)


# -----------------------------------------------------------------------------


_GOOGLE_IP_ADDR = "216.58.214.196"


class AutograderSandboxNetworkAccessTestCase(unittest.TestCase):

    def setUp(self):
        super().setUp()

        self.google_ping_cmd = ['ping', '-c', '5', _GOOGLE_IP_ADDR]

    def test_networking_disabled(self):
        with AutograderSandbox() as sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.returncode)

    def test_networking_enabled(self):
        with AutograderSandbox(allow_network_access=True) as sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertEqual(0, result.returncode)

    def test_set_allow_network_access(self):
        sandbox = AutograderSandbox()
        self.assertFalse(sandbox.allow_network_access)
        with sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.returncode)

        sandbox.allow_network_access = True
        self.assertTrue(sandbox.allow_network_access)
        with sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertEqual(0, result.returncode)

        sandbox.allow_network_access = False
        self.assertFalse(sandbox.allow_network_access)
        with sandbox:
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.returncode)

    def test_error_set_allow_network_access_while_running(self):
        with AutograderSandbox() as sandbox:
            with self.assertRaises(ValueError):
                sandbox.allow_network_access = True

            self.assertFalse(sandbox.allow_network_access)
            result = sandbox.run_command(self.google_ping_cmd)
            self.assertNotEqual(0, result.returncode)


class AutograderSandboxCopyFilesTestCase(unittest.TestCase):

    def test_copy_files_into_sandbox(self):
        files = []
        try:
            for i in range(10):
                f = typing.cast(typing.TextIO,
                                tempfile.NamedTemporaryFile(mode='w+'))
                f.write('this is file {}'.format(i))
                f.seek(0)
                files.append(f)

            filenames = [file_.name for file_ in files]

            with AutograderSandbox() as sandbox:
                sandbox.add_files(*filenames)

                ls_result = sandbox.run_command(['ls'])
                actual_filenames = [
                    filename.strip() for filename in ls_result.stdout.split()]
                expected_filenames = [
                    os.path.basename(filename) for filename in filenames]
                self.assertCountEqual(expected_filenames, actual_filenames)

                for file_ in files:
                    file_.seek(0)
                    expected_content = file_.read()
                    actual_content = sandbox.run_command(
                        ['cat', os.path.basename(file_.name)]).stdout
                    self.assertEqual(expected_content, actual_content)
        finally:
            for file_ in files:
                file_.close()

    def test_copy_and_rename_file_into_sandbox(self):
        expected_content = 'this is a file'
        with typing.cast(typing.TextIO, tempfile.NamedTemporaryFile('w+')) as f:
            f.write(expected_content)
            f.seek(0)

            with AutograderSandbox() as sandbox:
                new_name = 'new_filename.txt'
                sandbox.add_and_rename_file(f.name, new_name)

                ls_result = sandbox.run_command(['ls'])
                actual_filenames = [
                    filename.strip() for filename in ls_result.stdout.split()]
                expected_filenames = [new_name]
                self.assertCountEqual(expected_filenames, actual_filenames)

                actual_content = sandbox.run_command(['cat', new_name]).stdout
                self.assertEqual(expected_content, actual_content)


if __name__ == '__main__':
    unittest.main()
