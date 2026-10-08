#!/usr/bin/env python3
"""HTTP client — STARTER. Three TODOs to fill in.

Builds request bytes by hand over a TCP socket, so that when Wireshark shows
you a field you know which line of your code produced it.

    python3 client.py --path '/echo?name=ada&unit=7'
    python3 client.py -X POST --data 'hello from COM2512' --path /echo
    python3 client.py -X POST --form name=ada --form unit=7 --path /echo
    python3 client.py --raw ...        # also print the request you sent

Allowed: socket, urllib.parse, argparse, sys.
Not allowed: requests, http.client, urllib.request, or anything else that
builds the HTTP for you.
"""

import argparse
import socket
import sys
from urllib.parse import urlencode

RECV_SIZE = 4096
CRLF = b"\r\n"
HEADER_END = CRLF + CRLF


# ---------------------------------------------------------------------------
# TODO 1 — build the request bytes
# ---------------------------------------------------------------------------

def build_request(method: str, path: str, host: str, port: int,
                  body: bytes, content_type: str | None) -> bytes:
    """Assemble a complete HTTP/1.1 request as bytes.

    Target shape — note that EVERY line ends with CRLF, and that a blank line
    always separates headers from body even when there is no body:

        GET /echo?name=ada HTTP/1.1\\r\\n
        Host: 127.0.0.1:8080\\r\\n
        User-Agent: com2512-client/1.0\\r\\n
        Accept: */*\\r\\n
        Connection: close\\r\\n
        \\r\\n

    Rules:
      - Request line is 'METHOD TARGET HTTP/1.1'.
      - Host is MANDATORY in HTTP/1.1. Omit it and a real server answers 400.
        Format it 'host:port', except drop ':80' since port 80 is implied.
      - Only send Content-Type and Content-Length when there IS a body. Then
        Content-Length is len(body) in bytes — body is already bytes here, so
        len() is correct; the trap is counting a str instead.
      - Send 'Connection: close' so the server closes when done and your read
        loop in TODO 2 terminates on EOF.
      - You are joining bytes, not str. b'\\r\\n'.join([...]) + HEADER_END + body
        is one clean way.
    """
    raise NotImplementedError("TODO 1: build the request bytes")


# ---------------------------------------------------------------------------
# TODO 2 — connect, send, read the reply
# ---------------------------------------------------------------------------

def send_request(host: str, port: int, request: bytes, timeout: float) -> bytes:
    """Open a TCP connection, send the request, return the full response bytes.

    Steps:
      - socket.create_connection((host, port), timeout=timeout) — see
        ../sockets_demo.py. Use a `with` block so it closes on the way out.
      - sendall(request). Not send(): send() may write only part of the buffer
        and return a short count.
      - Read in a loop, accumulating chunks, until recv() returns b"" (EOF).
        One recv() will not reliably give you the whole response.

    Do NOT call shutdown(SHUT_WR) after sending. The server knows your request
    ended because Content-Length said so, not because the connection closed.
    That is HTTP framing doing its job, and it is what lets one connection
    carry many requests.
    """
    raise NotImplementedError("TODO 2: connect, sendall, recv until EOF")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="default: %(default)s")
    ap.add_argument("--port", type=int, default=8080, help="default: %(default)s")
    ap.add_argument("-X", "--method", default=None,
                    help="GET, POST, ... (default: POST when a body is given, else GET)")
    ap.add_argument("--path", default="/", help="request target (default: %(default)s)")
    ap.add_argument("--data", default=None, help="request body, sent as text/plain")
    ap.add_argument("--form", action="append", metavar="KEY=VALUE", default=[],
                    help="form field; repeatable. Sent application/x-www-form-urlencoded, "
                         "which Wireshark dissects field by field")
    ap.add_argument("--timeout", type=float, default=5.0, help="seconds (default: %(default)s)")
    ap.add_argument("--raw", action="store_true", help="print the request bytes we sent")
    args = ap.parse_args()

    if args.data is not None and args.form:
        print("use --data or --form, not both", file=sys.stderr)
        return 2

    # Given to you: works out the body and Content-Type from the flags.
    if args.form:
        pairs = []
        for item in args.form:
            key, sep, value = item.partition("=")
            if not sep:
                print(f"--form expects KEY=VALUE, got {item!r}", file=sys.stderr)
                return 2
            pairs.append((key, value))
        body = urlencode(pairs).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    elif args.data is not None:
        body = args.data.encode("utf-8")
        content_type = "text/plain; charset=utf-8"
    else:
        body = b""
        content_type = None

    method = args.method or ("POST" if body else "GET")

    request = build_request(method, args.path, args.host, args.port, body, content_type)

    if args.raw:
        print("--- request sent ---")
        print(request.decode("utf-8", errors="replace").replace("\r\n", "\\r\\n\n"))
        print("--- end ---\n")

    try:
        response = send_request(args.host, args.port, request, args.timeout)
    except (OSError, socket.timeout) as exc:
        print(f"request to {args.host}:{args.port} failed: {exc}", file=sys.stderr)
        print("is your server running?", file=sys.stderr)
        return 1

    if not response:
        print("server closed without sending a response", file=sys.stderr)
        return 1

    # TODO 3 — print the raw response exactly as it arrived, decoded as UTF-8
    # with errors="replace". Do not parse it, do not prettify it: you want to
    # see the status line, the headers, the blank line and the body as they came
    # off the wire. Then `return 0` — main() has to return an exit code.
    raise NotImplementedError("TODO 3: print the raw response")


if __name__ == "__main__":
    raise SystemExit(main())
