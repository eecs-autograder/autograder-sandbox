import argparse
import os
import tempfile
import time

from autograder_sandbox import AutograderSandbox, SandboxCommandError, VERSION


def main():
    args = parse_args()

    stdin = tempfile.NamedTemporaryFile()

    repeat_str = b'a' * 1000
    num_repeats = args.output_size // 1000
    remainder = args.output_size % 1000
    for i in range(num_repeats):
        stdin.write(repeat_str)
    stdin.write(b'a' * remainder)

    with AutograderSandbox() as sandbox:
        stdin.seek(0)
        start = time.time()
        result = sandbox.run_command(['cat'], stdin=stdin)
        print('Ran command that read and printed {} bytes to stdout in {}'.format(
            args.output_size, time.time() - start))
        stdout_size = os.path.getsize(result.stdout.name)
        print(stdout_size)
        assert args.output_size == stdout_size

    if args.stderr:
        with AutograderSandbox() as sandbox:
            stdin.seek(0)
            start = time.time()
            result = sandbox.run_command(['bash', '-c', '>&2 cat'], stdin=stdin)
            print('Ran command that read and printed {} bytes to stderr in {}'.format(
                num_repeats * len(repeat_str), time.time() - start))
            stderr_size = os.path.getsize(result.stderr.name)
            print(stderr_size)
            assert args.output_size == stderr_size


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('output_size', type=int)
    parser.add_argument('--stderr', action='store_true', default=False)

    return parser.parse_args()


if __name__ == '__main__':
    main()
