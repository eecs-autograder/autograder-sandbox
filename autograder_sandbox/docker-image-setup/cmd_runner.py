#! /usr/bin/python3

import os
import sys
import subprocess
import pwd
import argparse
import resource
import grp


# KEEP UP TO DATE WITH SANDBOX_USERNAME IN autograder_sandbox.py
SANDBOX_USERNAME = 'autograder'


def main() -> None:
    args = parse_args()

    def set_subprocess_rlimits() -> None:
        try:
            if args.as_root:
                os.setgid(0)
                os.setuid(0)
            else:
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
                        resource.RLIMIT_VMEM,  # type: ignore
                        (args.max_virtual_memory, args.max_virtual_memory))
                except Exception:
                    resource.setrlimit(
                        resource.RLIMIT_AS,
                        (args.max_virtual_memory, args.max_virtual_memory))

        except Exception:
            import traceback
            print('Internal AutograderSandbox error while setting up command', file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

    env_copy = os.environ.copy()
    if not args.as_root:
        record = pwd.getpwnam('autograder')
        env_copy['HOME'] = record.pw_dir
        env_copy['USER'] = record.pw_name
        env_copy['LOGNAME'] = record.pw_name

    try:
        result = subprocess.run(
            args.cmd_args,
            env=env_copy,
            start_new_session=False,
            preexec_fn=set_subprocess_rlimits
        )
        sys.exit(result.returncode)
    except (FileNotFoundError, NotADirectoryError) as e:
        print('Command "{}" not found'.format(args.cmd_args[0]), file=sys.stderr)
        sys.exit(127)
    except PermissionError as e:
        print(
            'Permission denied: Command "{}" not executable'.format(args.cmd_args[0]),
            file=sys.stderr
        )
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cmd_id",
        help='A unique id that the caller can use to find the process '
             'in which this command is running.'
    )
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


if __name__ == '__main__':
    main()
