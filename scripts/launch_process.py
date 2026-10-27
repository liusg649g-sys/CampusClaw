"""Detach one service with explicit handles; never inherit launcher console pipes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

def main():
    if sys.argv[1:]==['--open-browser']:
        os.startfile('http://127.0.0.1:8080/')
        return
    parser=argparse.ArgumentParser()
    parser.add_argument('--cwd',required=True)
    parser.add_argument('--stdout',required=True)
    parser.add_argument('--stderr',required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if os.name!='nt' or not args.command:
        parser.error('Windows service command required')
    # Append preserves diagnostics across successive launches. Only log files are
    # opened here; account/material/database files are not touched.
    with Path(args.stdout).open('ab') as output,Path(args.stderr).open('ab') as errors:
        child=subprocess.Popen(args.command,cwd=args.cwd,stdin=subprocess.DEVNULL,
            stdout=output,stderr=errors,close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
    print(child.pid)

if __name__=='__main__':main()
