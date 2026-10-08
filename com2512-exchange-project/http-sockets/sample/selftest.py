#!/usr/bin/env python3
"""Proves the sample server and client work on your machine. No network needed.

    python3 selftest.py

Starts echo_server.py on a free port, drives a GET and a POST through
http_client.py, and checks the responses. Run this before the lab so you are
debugging HTTP, not your Python install.
"""

import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "echo_server.py"
CLIENT = HERE / "http_client.py"


def free_port() -> int:
    """Ask the OS for an unused port by binding to 0 and reading it back."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_banner(server: subprocess.Popen) -> str | None:
    """Wait for the server's 'listening on ...' line on stdout.

    We deliberately do not probe by opening a TCP connection: the server runs
    with --once here, so a probe connection would be counted as the request and
    the server would exit before the real client arrived.

    Returns the banner line, or None if the server died first.
    """
    line = server.stdout.readline()
    return line if line.startswith("listening on") else None


def run_case(name: str, port: int, client_args: list[str], expect: list[str]) -> bool:
    server = subprocess.Popen(
        [sys.executable, str(SERVER), "--port", str(port), "--once"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if wait_for_banner(server) is None:
            print(f"FAIL {name}: server never came up")
            return False

        client = subprocess.run(
            [sys.executable, str(CLIENT), "--port", str(port)] + client_args,
            capture_output=True, text=True, timeout=10)
        server_out = server.communicate(timeout=10)[0]
    finally:
        if server.poll() is None:
            server.kill()

    problems = []
    if client.returncode != 0:
        problems.append(f"client exited {client.returncode}: {client.stderr.strip()}")
    if "HTTP/1.1 200 OK" not in client.stdout:
        problems.append("no 200 OK in the response")
    for needle in expect:
        if needle not in client.stdout:
            problems.append(f"response missing {needle!r}")
        if needle not in server_out:
            problems.append(f"server stdout missing {needle!r}")

    if problems:
        print(f"FAIL {name}")
        for problem in problems:
            print(f"     - {problem}")
        return False

    print(f"ok   {name}")
    return True


def main() -> int:
    for path in (SERVER, CLIENT):
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            return 1

    cases = [
        ("GET /", ["--path", "/"], ["GET / HTTP/1.1", "Host: 127.0.0.1"]),
        ("GET with query", ["--path", "/hello?name=ada"], ["GET /hello?name=ada HTTP/1.1"]),
        ("POST text/plain", ["-X", "POST", "--data", "hello from COM2512"],
         ["POST / HTTP/1.1", "Content-Length: 18", "hello from COM2512"]),
        ("POST form", ["-X", "POST", "--form", "name=ada", "--form", "unit=7"],
         ["application/x-www-form-urlencoded", "name=ada&unit=7"]),
    ]

    passed = sum(run_case(name, free_port(), args, expect) for name, args, expect in cases)
    total = len(cases)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
