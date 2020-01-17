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
    stdin = tempfile.NamedTemporaryFile()

    repeat_str = b'a' * 1000
    num_repeats = output_size // 1000
    remainder = output_size % 1000
    for i in range(num_repeats):
        stdin.write(repeat_str)
    stdin.write(b'a' * remainder)

    with AutograderSandbox() as sandbox:
        stdin.seek(0)
        start = time.time()
        result = sandbox.run_command(
            ['python3', '-c', _STDIN_TO_STDOUT_PROG],
            stdin=stdin, truncate_stdout=truncate, truncate_stderr=truncate)
        print('Ran command that read and printed {} bytes to stdout in {}'.format(
            output_size, time.time() - start))
        stdout_size = os.path.getsize(result.stdout.name)
        print(stdout_size)
        if truncate is None:
            assert stdout_size == output_size
        else:
            assert stdout_size == truncate

    if stderr:
        with AutograderSandbox() as sandbox:
            stdin.seek(0)
            start = time.time()
            result = sandbox.run_command(
                ['python3', '-c', _STDIN_TO_STDERR_PROG],
                stdin=stdin, truncate_stdout=truncate, truncate_stderr=truncate)
            print('Ran command that read and printed {} bytes to stderr in {}'.format(
                num_repeats * len(repeat_str), time.time() - start))
            stderr_size = os.path.getsize(result.stderr.name)
            print(stderr_size)
            if truncate is None:
                assert stderr_size == output_size
            else:
                assert stderr_size == truncate


_STDIN_TO_STDOUT_PROG = """
import shutil
import sys

while True:
    chunk = sys.stdin.read()
    if not chunk:
        break

    sys.stdout.write(chunk)
    sys.stdout.flush()
"""

_STDIN_TO_STDERR_PROG = """
import shutil
import sys

shutil.copyfileobj(sys.stdin, sys.stderr)
"""

if __name__ == '__main__':
    main()
