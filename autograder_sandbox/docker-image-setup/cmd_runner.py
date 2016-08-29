#! /usr/bin/env python3

import os
import sys
import subprocess
import argparse
import resource


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

    return_code = subprocess.call(args.cmd_args,
                                  preexec_fn=set_subprocess_rlimits)
    sys.exit(return_code)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_num_processes", nargs='?', type=int)
    parser.add_argument("--max_stack_size", nargs='?', type=int)
    parser.add_argument("--max_virtual_memory", nargs='?', type=int)
    parser.add_argument("--linux_user_id", nargs='?', type=int)
    parser.add_argument("cmd_args", nargs=argparse.REMAINDER)

    return parser.parse_args()


if __name__ == '__main__':
    main()
