#! /usr/bin/env python3

import os
import sys
import subprocess
import signal
import argparse
import resource
import json
import tempfile

import shutil


def main():
    args = parse_args()

    def set_subprocess_rlimits():
        try:
            if args.linux_user_id is not None:
                os.setuid(args.linux_user_id)

            if args.max_num_processes is not None:
                resource.setrlimit(
                    resource.RLIMIT_NPROC,
                    (args.max_num_processes, args.max_num_processes))

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

    # Adopted from https://github.com/python/cpython/blob/3.5/Lib/subprocess.py#L378
    stdout = b''
    stderr = b''
    timed_out = False
    return_code = None
    stdin = subprocess.DEVNULL if args.stdin_devnull else None
    try:
        with subprocess.Popen(args.cmd_args,
                              stdin=stdin,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              preexec_fn=set_subprocess_rlimits,
                              start_new_session=True) as process:
            try:
                stdout, stderr = process.communicate(None, timeout=args.timeout)
                return_code = process.poll()
            except subprocess.TimeoutExpired:
                # http://stackoverflow.com/questions/4789837/how-to-terminate-a-python-subprocess-launched-with-shell-true
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                stdout, stderr = process.communicate()
                timed_out = True
            except:  # noqa
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait()
                raise
    except FileNotFoundError:
        # This is the value returned by /bin/sh when an executable could
        # not be found.
        return_code = 127

    results = {
        'cmd_args': args.cmd_args,
        'return_code': return_code,
        'timed_out': timed_out,
        'stdout_truncated': False,
        'stderr_truncated': False
    }

    if args.truncate_stdout is not None and len(stdout) > args.truncate_stdout:
        stdout = stdout[:args.truncate_stdout]
        results['stdout_truncated'] = True

    if args.truncate_stderr is not None and len(stderr) > args.truncate_stderr:
        stderr = stderr[:args.truncate_stderr]
        results['stderr_truncated'] = True

    json_data = json.dumps(results)
    print(len(json_data), flush=True)
    print(json_data, end='', flush=True)

    print(len(stdout), flush=True)
    sys.stdout.buffer.write(stdout)
    sys.stdout.flush()

    print(len(stderr), flush=True)
    sys.stdout.buffer.write(stderr)
    sys.stdout.flush()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", nargs='?', type=int)
    parser.add_argument("--max_num_processes", nargs='?', type=int)
    parser.add_argument("--max_stack_size", nargs='?', type=int)
    parser.add_argument("--max_virtual_memory", nargs='?', type=int)
    parser.add_argument("--truncate_stdout", nargs='?', type=int)
    parser.add_argument("--truncate_stderr", nargs='?', type=int)
    parser.add_argument("--linux_user_id", nargs='?', type=int)
    parser.add_argument("--stdin_devnull", action='store_true', default=False)
    parser.add_argument("cmd_args", nargs=argparse.REMAINDER)

    return parser.parse_args()


if __name__ == '__main__':
    main()
