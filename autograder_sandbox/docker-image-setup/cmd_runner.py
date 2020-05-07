#! /usr/bin/python3

import os
import sys
import subprocess
import signal
import pwd
import argparse
import resource
import json
import tempfile
import uuid
import shutil
import grp


# KEEP UP TO DATE WITH SANDBOX_USERNAME IN autograder_sandbox.py
SANDBOX_USERNAME = 'autograder'


def main():
    args = parse_args()

    def set_subprocess_rlimits():
        try:
            if not args.as_root:
                os.setgid(grp.getgrnam('autograder').gr_gid)
                os.setuid(pwd.getpwnam('autograder').pw_uid)

            if args.block_process_spawn:
                resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))

            if args.max_stack_size is not None:
                resource.setrlimit(
                    resource.RLIMIT_STACK,
                    (args.max_stack_size, args.max_stack_size))

            if args.max_virtual_memory is not None:
                try:
                    resource.setrlimit(
                        resource.RLIMIT_VMEM,
                        (args.max_virtual_memory, args.max_virtual_memory))
                except Exception:
                    resource.setrlimit(
                        resource.RLIMIT_AS,
                        (args.max_virtual_memory, args.max_virtual_memory))

        except Exception:
            import traceback
            traceback.print_exc()
            raise

    timed_out = False
    return_code = None
    stdin = subprocess.DEVNULL if args.stdin_devnull else None
    # IMPORTANT: We want to use NamedTemporaryFile here rather than TemporaryFile
    # so that we can determine output size with os.path.size(). In some cases,
    # notably when valgrind produces a core dump, file.tell() produces a value
    # that is too large, which then causes an error.
    with tempfile.NamedTemporaryFile() as stdout, tempfile.NamedTemporaryFile() as stderr:
        # Adopted from https://github.com/python/cpython/blob/3.5/Lib/subprocess.py#L378
        env_copy = os.environ.copy()
        if not args.as_root:
            record = pwd.getpwnam('autograder')
            env_copy['HOME'] = record.pw_dir
            env_copy['USER'] = record.pw_name
            env_copy['LOGNAME'] = record.pw_name
        try:
            with subprocess.Popen(args.cmd_args,
                                  stdin=stdin,
                                  stdout=stdout,
                                  stderr=stderr,
                                  preexec_fn=set_subprocess_rlimits,
                                  start_new_session=True,
                                  env=env_copy) as process:
                try:
                    process.communicate(None, timeout=args.timeout)
                    return_code = process.poll()
                except subprocess.TimeoutExpired:
                    # http://stackoverflow.com/questions/4789837/how-to-terminate-a-python-subprocess-launched-with-shell-true
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()
                    timed_out = True
                except:  # noqa
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()
                    raise

        except FileNotFoundError:
            # This is the value returned by /bin/sh when an executable could
            # not be found.
            return_code = 127

        stdout_len = os.path.getsize(stdout.name)
        stdout_truncated = (
            args.truncate_stdout is not None and stdout_len > args.truncate_stdout)
        stderr_len = os.path.getsize(stderr.name)
        stderr_truncated = (
            args.truncate_stderr is not None and stderr_len > args.truncate_stderr)
        results = {
            'cmd_args': args.cmd_args,
            'return_code': return_code,
            'timed_out': timed_out,
            'stdout_truncated': stdout_truncated,
            'stderr_truncated': stderr_truncated,
        }

        json_data = json.dumps(results)
        print(len(json_data), flush=True)
        print(json_data, end='', flush=True)

        truncated_stdout_len = args.truncate_stdout if stdout_truncated else stdout_len
        print(truncated_stdout_len, flush=True)
        stdout.seek(0)
        for chunk in _chunked_read(stdout, truncated_stdout_len):
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()

        truncated_stderr_len = args.truncate_stderr if stderr_truncated else stderr_len
        print(stderr_len, flush=True)
        stderr.seek(0)
        for chunk in _chunked_read(stderr, truncated_stderr_len):
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--block_process_spawn", action='store_true', default=False)
    parser.add_argument("--max_stack_size", type=int)
    parser.add_argument("--max_virtual_memory", type=int)
    parser.add_argument("--truncate_stdout", type=int)
    parser.add_argument("--truncate_stderr", type=int)
    parser.add_argument("--as_root", action='store_true', default=False)
    parser.add_argument("--stdin_devnull", action='store_true', default=False)
    parser.add_argument("cmd_args", nargs=argparse.REMAINDER)

    return parser.parse_args()


# Generator that reads amount_to_read bytes from file_obj, yielding
# one chunk at a time.
def _chunked_read(file_obj, amount_to_read, chunk_size=1024 * 16):
    num_reads = amount_to_read // chunk_size
    for i in range(num_reads):
        yield file_obj.read(chunk_size)

    remainder = amount_to_read % chunk_size
    if remainder:
        yield file_obj.read(remainder)


if __name__ == '__main__':
    main()
