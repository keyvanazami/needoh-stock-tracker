#!/usr/bin/env python3
"""An HTTP client that builds its request bytes by hand over a TCP socket.

No http.client, no requests. You assemble the request line, the headers, the
blank line and the body yourself, so when Wireshark shows you a field you know
exactly which line of code produced it.

    python3 http_client.py                                    # GET /
    python3 http_client.py --path '/hello?name=ada'            # GET with a query
    python3 http_client.py -X POST --data 'hello from COM2512' # POST text/plain
    python3 http_client.py -X POST --form name=ada --form unit=7  # urlencoded form
    python3 http_client.py --raw                               # also echo what we sent
"""

import argparse
import socket
import sys
from urllib.parse import urlencode

RECV_SIZE = 4096
CRLF = b"\r\n"
HEADER_END = CRLF + CRLF


def build_request(method: str, path: str, host: str, port: int,
                  body: bytes, content_type: str | None) -> bytes:
    """Assemble a complete HTTP/1.1 request.

    Three rules worth memorising:
      1. Lines end with CRLF (\\r\\n), not \\n. A bare \\n is not HTTP.
      2. A blank line separates headers from body -- always present, even with
         no body, which is why the terminator is \\r\\n\\r\\n.
      3. HTTP/1.1 requires the Host header. Omit it and a real server answers
         400 Bad Request.
    """
    lines = [f"{method} {path} HTTP/1.1".encode("ascii")]

    # Port 80 is implied by scheme, so it is conventionally left off Host.
    host_value = host if port == 80 else f"{host}:{port}"
    lines.append(f"Host: {host_value}".encode("ascii"))
    lines.append(b"User-Agent: com2512-client/1.0")
    lines.append(b"Accept: */*")

    if body:
        # Content-Length is how the server knows where the body stops. Without
        # it the server has no way to tell "body finished" from "still sending".
        lines.append(f"Content-Type: {content_type}".encode("ascii"))
        lines.append(f"Content-Length: {len(body)}".encode("ascii"))

    # Ask the server to close when done, so reading until EOF gets the response.
    lines.append(b"Connection: close")

    return CRLF.join(lines) + HEADER_END + body


def send_request(host: str, port: int, request: bytes, timeout: float) -> bytes:
    """Open a TCP connection, send the request, read the response until EOF."""
    # create_connection() does getaddrinfo + socket() + connect() for us and
    # handles IPv4/IPv6. The long-hand equivalent is:
    #     sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #     sock.connect((host, port))
    with socket.create_connection((host, port), timeout=timeout) as sock:
        # sendall() loops until every byte is handed to the kernel. Plain send()
        # may write only part of the buffer and return a short count -- another
        # classic bug in hand-rolled clients.
        sock.sendall(request)

        # Note what we do NOT do here: we never call shutdown(SHUT_WR). The
        # server knows the request ended because Content-Length said so, not
        # because the connection closed. That is HTTP framing doing its job.
        chunks = []
        while True:
            chunk = sock.recv(RECV_SIZE)
            if not chunk:  # empty bytes means the peer closed -- true EOF
                break
            chunks.append(chunk)
    return b"".join(chunks)


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
        print("is the echo server running?", file=sys.stderr)
        return 1

    if not response:
        print("server closed without sending a response", file=sys.stderr)
        return 1

    print("--- response received ---")
    print(response.decode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
