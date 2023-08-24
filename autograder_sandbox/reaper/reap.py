#! /usr/bin/env python3.10

"""
Used by the autograder_sandbox libary to reap process trees.
Not intended for general-purpose use.
Requires python 3.10 or later.
"""

import argparse
import os

import psutil


def main() -> None:
    args = parse_args()
    _reap(args.search_for)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('search_for')

    return parser.parse_args()


def _reap(search_for: str) -> None:
    """
    Search for the process that contains "search_for" in its command line
    arguments. search_for should be either the unique main container process
    or the unique ID included in a call to cmd_runner.py

    Finds and kills the process tree whose root is the found process.
    Does not kill the root of the tree.
    """
    try:
        if (parent_proc := _find_process(search_for)) is not None:
            print(f'Reaping children of {search_for} {parent_proc.cmdline()}', flush=True)
            _kill_proc_descendents(parent_proc)
    except psutil.NoSuchProcess:
        pass


def _find_process(search_for: str) -> 'psutil.Process | None':
    print(f'Searching for process {search_for}', flush=True)
    for p in psutil.process_iter():
        try:
            cmd_args = p.cmdline()
            if cmd_args[:2] == ['docker', 'exec']:
                continue

            for arg in cmd_args:
                if search_for in arg:
                    return p
        except psutil.NoSuchProcess:
            continue

    return None


# Adapted from: https://psutil.readthedocs.io/en/latest/#kill-process-tree
# and https://psutil.readthedocs.io/en/latest/#psutil.wait_procs
def _kill_proc_descendents(parent: psutil.Process) -> None:
    """
    Kill a process's descendents (including grandchildren),
    first sending SIGTERM, waiting, and then sending SIGKILL to the ones
    that haven't exited
    "sig" and return a (gone, still_alive) tuple.
    "on_terminate", if specified, is a callback function which is
    called as soon as a child terminates.
    """
    try:
        assert parent.pid != os.getpid(), \
            "_kill_proc_descendents called with pid of current process"
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        return

    print(f'Children {children}', flush=True)  # FIXME
    print('Sending SIGTERM to children', flush=True)
    for p in children:
        try:
            print(f'Sending SIGTERM to {p.cmdline()} (pid={p.pid})', flush=True)
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    print('Waiting for terminated procs', flush=True)
    gone, alive = psutil.wait_procs(children, timeout=3)
    print('Sending SIGKILL to remaining children', flush=True)
    for p in alive:
        try:
            print(f'Sending SIGKILL to {p.cmdline()} (pid={p.pid})', flush=True)
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


if __name__ == '__main__':
    main()
