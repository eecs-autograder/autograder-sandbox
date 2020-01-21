import argparse
import os
import tempfile
import time

from autograder_sandbox import AutograderSandbox, SandboxCommandError, VERSION


def main():
    args = parse_args()
    output_size_performance_test(args.output_size, stderr=args.stderr, truncate=args.truncate)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('output_size', type=int)
    parser.add_argument('--stderr', action='store_true', default=False)
    parser.add_argument('--truncate', type=int)

    return parser.parse_args()


def output_size_performance_test(output_size, *, stderr=True, truncate=None):
    with AutograderSandbox() as sandbox:
        start = time.time()
        result = sandbox.run_command(
            ['python3', '-c', _PRINT_PROG.format(output_size, stream='stdout')],
            truncate_stdout=truncate, truncate_stderr=truncate, check=True)
        print('Ran command that printed {} bytes to stdout in {}'.format(
            output_size, time.time() - start))
        stdout_size = os.path.getsize(result.stdout.name)
        print(stdout_size)
        if truncate is None:
            assert stdout_size == output_size
        else:
            assert stdout_size == truncate

    if stderr:
        with AutograderSandbox() as sandbox:
            start = time.time()
            result = sandbox.run_command(
                ['python3', '-c', _PRINT_PROG.format(output_size, stream='stderr')],
                truncate_stdout=truncate, truncate_stderr=truncate, check=True)
            print('Ran command that printed {} bytes to stderr in {}'.format(
                output_size, time.time() - start))
            stderr_size = os.path.getsize(result.stderr.name)
            print(stderr_size)
            if truncate is None:
                assert stderr_size == output_size
            else:
                assert stderr_size == truncate


_PRINT_PROG = """
import sys

output_size = {}
repeat_str = 'a' * 1000
num_repeats = output_size // 1000
remainder = output_size % 1000
for i in range(num_repeats):
    sys.{stream}.write(repeat_str)
    sys.{stream}.flush()
sys.{stream}.write('a' * remainder)
sys.{stream}.flush()
"""

if __name__ == '__main__':
    main()
