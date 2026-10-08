#!/usr/bin/env python3
"""Checks your server.py against the requirements. Run it as you work.

    python3 check.py              # expects ./server.py
    python3 check.py --port 8099  # if 8080 is busy

It sends raw HTTP over a socket itself, so it does not need your client.py —
you can finish the server first. Nine checks; all nine passing means your
server meets the spec. It does not check your client, your capture, or your
screenshots.
"""

import argparse
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CRLF = b"\r\n"
HEADER_END = CRLF + CRLF


def raw(port, request, timeout=4.0, split_after_headers=False):
    """Send raw request bytes, return the full response bytes (b'' on timeout)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            if split_after_headers and HEADER_END in request:
                head, _, body = request.partition(HEADER_END)
                sock.sendall(head + HEADER_END)
                time.sleep(0.15)      # force headers and body into separate reads
                sock.sendall(body)
            else:
                sock.sendall(request)
            out = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                out += chunk
            return out
    except (OSError, socket.timeout):
        return b""


def parse(response):
    """Split a response into (status_line, headers_dict, body). Lowercase keys."""
    head, _, body = response.partition(HEADER_END)
    lines = head.split(CRLF)
    status = lines[0].decode("latin-1") if lines else ""
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(b":")
        if sep:
            headers[name.strip().lower().decode("latin-1")] = value.strip()
    return status, headers, body


def req(method, target, body=b"", extra=()):
    """Build a well-formed request. `extra` adds or overrides header lines."""
    lines = [f"{method} {target} HTTP/1.1".encode(), b"Host: 127.0.0.1"]
    if body and not any(h.lower().startswith(b"content-length") for h in extra):
        lines.append(b"Content-Length: " + str(len(body)).encode())
    lines.extend(extra)
    lines.append(b"Connection: close")
    return CRLF.join(lines) + HEADER_END + body


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--server", default=str(HERE / "server.py"))
    args = ap.parse_args()

    if not Path(args.server).exists():
        print(f"cannot find {args.server}", file=sys.stderr)
        return 1

    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    server = subprocess.Popen([sys.executable, args.server, "--port", str(args.port)],
                              stdout=log, stderr=subprocess.STDOUT, text=True)

    # Wait for the banner line rather than probing with a connection, which on a
    # --once server would be counted as the request.
    banner, deadline = False, time.monotonic() + 6
    while time.monotonic() < deadline:
        if server.poll() is not None:
            break
        if "listening on" in Path(log.name).read_text():
            banner = True
            break
        time.sleep(0.05)

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    if not banner:
        tail = Path(log.name).read_text().strip().splitlines()[-6:]
        check("server starts and prints 'listening on ...'", False,
              "no banner. Server output:\n      " + "\n      ".join(tail))
    else:
        check("server starts and prints 'listening on ...'", True)

        # 1. GET with a query string
        status, _, body = parse(raw(args.port, req("GET", "/echo?name=ada&unit=7")))
        check("GET /echo?name=ada&unit=7 -> 200 listing both parameters",
              "200" in status and b"name=ada" in body and b"unit=7" in body,
              f"status={status!r} body={body[:80]!r}")

        # 2. POST echoes the body verbatim
        status, _, body = parse(raw(args.port, req("POST", "/echo", b"hello from COM2512")))
        check("POST /echo -> 200 echoing the body verbatim",
              "200" in status and b"hello from COM2512" in body,
              f"status={status!r} body={body[:80]!r}")

        # 3. 404 for anything else
        status, _, _ = parse(raw(args.port, req("GET", "/nowhere")))
        check("GET /nowhere -> 404", "404" in status, f"status={status!r}")

        # 4. Content-Length is a byte count, not a character count
        payload = "price: £5 — ok".encode("utf-8")
        status, headers, body = parse(raw(args.port, req("POST", "/echo", payload)))
        declared = headers.get("content-length", b"")
        check("Content-Length counts bytes, not characters (non-ASCII body)",
              "200" in status and declared.isdigit() and int(declared) == len(body)
              and payload in body,
              f"declared={declared!r} actual={len(body)} body={body[:60]!r}")

        # 5. Framing: headers and body arriving in separate reads
        status, _, body = parse(raw(args.port, req("POST", "/echo", b"split across reads"),
                                    split_after_headers=True))
        check("handles headers and body arriving in separate recv() calls",
              "200" in status and b"split across reads" in body,
              f"status={status!r} body={body[:80]!r} "
              "(your recv loop probably assumed one recv == one request)")

        # 6. Malformed Content-Length must not crash the server
        raw(args.port, req("POST", "/echo", b"x" * 10,
                           extra=(b"Content-Length: abc",)))
        status, _, _ = parse(raw(args.port, req("GET", "/echo?after=malformed")))
        check("survives a non-numeric Content-Length", "200" in status,
              f"server stopped answering after a bad header; status={status!r}")

        # 7. A client that connects and sends nothing
        try:
            socket.create_connection(("127.0.0.1", args.port), timeout=2).close()
        except OSError:
            pass
        status, _, _ = parse(raw(args.port, req("GET", "/echo?after=silence")))
        check("survives a client that connects and sends nothing", "200" in status,
              f"server stopped answering; status={status!r}")

        # 8. Sequential clients (checks 1-7 already relied on this, so this is
        #    really a restatement — but it localises the failure if it is broken)
        oks = ["200" in parse(raw(args.port, req("GET", f"/echo?n={i}")))[0]
               for i in range(3)]
        check("serves a sequence of clients without exiting", all(oks),
              f"results={oks}")

    if server.poll() is None:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
    log.flush()
    server_out = Path(log.name).read_text()

    # 9. The request is echoed to stdout
    if banner:
        check("echoes requests to stdout (headers and body)",
              "GET /echo?name=ada&unit=7" in server_out
              and "hello from COM2512" in server_out,
              "stdout did not contain the request line and body we sent")

        # Only meaningful once the server actually started: before that, the
        # traceback is just the unimplemented TODO telling you where to begin.
        if "Traceback" in server_out:
            check("no tracebacks in server output", False,
                  "found a Traceback — a malformed request must not crash the server")

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'}  {name.ljust(width)}")
        if not ok and detail:
            print(f"      {detail}")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        print(f"full server output: {log.name}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
