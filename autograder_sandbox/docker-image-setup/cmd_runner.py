#! /usr/bin/env python3

import os
import sys
import subprocess
import signal
import argparse
import resource
import json


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
    stdout = None
    stderr = None
    timed_out = False
    return_code = None
    with subprocess.Popen(args.cmd_args,
                          stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,
                          preexec_fn=set_subprocess_rlimits,
                          start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(
                sys.stdin.buffer.read(), timeout=args.timeout)
            return_code = process.poll()
        except subprocess.TimeoutExpired:
            # http://stackoverflow.com/questions/4789837/how-to-terminate-a-python-subprocess-launched-with-shell-true
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            stdout, stderr = process.communicate()
            timed_out = True
        except:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()
            raise

    results = {
        'cmd_args': args.cmd_args,
        'stdout': stdout.decode(args.encoding, errors=args.encoding_error_policy),
        'stderr': stderr.decode(args.encoding, errors=args.encoding_error_policy),
        'return_code': return_code,
        'timed_out': timed_out
    }
    print(json.dumps(results))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", nargs='?', type=int)
    parser.add_argument("--max_num_processes", nargs='?', type=int)
    parser.add_argument("--max_stack_size", nargs='?', type=int)
    parser.add_argument("--max_virtual_memory", nargs='?', type=int)
    parser.add_argument("--linux_user_id", nargs='?', type=int)
    parser.add_argument("--encoding", nargs='?')
    parser.add_argument("--encoding_error_policy", nargs='?')
    parser.add_argument("cmd_args", nargs=argparse.REMAINDER)

    return parser.parse_args()


if __name__ == '__main__':
    main()
