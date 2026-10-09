#!/usr/bin/env python3
"""Primary CLI entrypoint for the SNP project."""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def _run_git(args):
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def cmd_serve(args):
    from main import run_server

    run_server(args.host, args.port)


def cmd_send(args):
    from main import run_client

    run_client(args.host, args.port, args.message)


def cmd_test(args):
    cmd = [sys.executable, "-m", "unittest", "-q"]
    if args.pattern:
        cmd.extend(["-k", args.pattern])
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def cmd_update(args):
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("This directory is not a git repository.", file=sys.stderr)
        return 1

    steps = [
        ["fetch", "--all", "--prune"],
        ["reset", "--hard", args.branch],
        ["clean", "-fd"],
        ["pull", "--ff-only", "origin", args.branch.split("/", 1)[-1]],
    ]

    for step in steps:
        code = _run_git(step)
        if code != 0:
            return code

    print(f"Repository updated from {args.branch}.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Shivi Network Protocol (SNP)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start an SNP server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=9000)
    serve_parser.set_defaults(func=cmd_serve)

    send_parser = subparsers.add_parser("send", help="Send a message to an SNP server")
    send_parser.add_argument("message")
    send_parser.add_argument("--host", default="127.0.0.1")
    send_parser.add_argument("--port", type=int, default=9000)
    send_parser.set_defaults(func=cmd_send)

    test_parser = subparsers.add_parser("test", help="Run the project test suite")
    test_parser.add_argument("--pattern", help="Optional unittest pattern filter")
    test_parser.set_defaults(func=cmd_test)

    update_parser = subparsers.add_parser("update", help="Fetch and replace the local repo with the latest remote code")
    update_parser.add_argument("--branch", default="origin/main", help="Remote branch to sync from")
    update_parser.set_defaults(func=cmd_update)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "func"):
            return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
