#!/usr/bin/env python3
"""HTTP echo server — STARTER. Six TODOs to fill in.

Run it and it exits with NotImplementedError. That is expected: the work is
yours. Read ../sockets_demo.py first for the socket calls themselves.

    python3 server.py                 # listen on 127.0.0.1:8080
    python3 server.py --show-crlf     # print \\r\\n literally, very useful
    python3 check.py                  # tells you which TODOs still fail

Allowed: socket, urllib.parse, argparse, sys.
Not allowed: http.server, http.client, socketserver, requests, Flask, or any
other library that speaks HTTP for you. Writing the bytes is the assignment.
"""

import argparse
import socket
import sys
from urllib.parse import parse_qsl, urlsplit

HOST = "127.0.0.1"
PORT = 8080
RECV_SIZE = 4096
CRLF = b"\r\n"
HEADER_END = CRLF + CRLF   # a blank line ends the header block


# ---------------------------------------------------------------------------
# Given to you. Not part of the assignment.
# ---------------------------------------------------------------------------

def show(data: bytes, mark_crlf: bool) -> str:
    """Render request bytes for a human, optionally making CRLFs visible."""
    text = data.decode("utf-8", errors="replace")
    if mark_crlf:
        text = text.replace("\r\n", "\\r\\n\n")
    return text


# ---------------------------------------------------------------------------
# TODO 1 — parse the Content-Length header
# ---------------------------------------------------------------------------

def content_length(head: bytes) -> int:
    """Return the Content-Length value from a header block, or 0 if absent.

    `head` is the bytes before the blank line, e.g.

        b'POST /echo HTTP/1.1\\r\\nHost: h\\r\\nContent-Length: 12'

    Requirements:
      - Split on CRLF. Skip the FIRST line: that is the request line, not a header.
      - Header names are case-insensitive. 'content-length' must match too.
      - Return 0 when the header is missing.
      - Return 0 when the value is not a number — do NOT let ValueError escape.
        A malformed request must never crash your server.
    """
    raise NotImplementedError("TODO 1: parse Content-Length")


# ---------------------------------------------------------------------------
# TODO 2 — read exactly one request off the connection
# ---------------------------------------------------------------------------

def recv_request(conn: socket.socket) -> bytes | None:
    """Read one complete HTTP request. Return None if the peer sent nothing.

    This is the TODO people get wrong, so read carefully.

    recv() hands back whatever has arrived. It may give you half a header line,
    or the headers plus part of the body, or (if the client is slow) the headers
    now and the body 50ms later. One recv() is NOT one request.

    So, in two phases:

      Phase 1 — headers. Loop recv() and accumulate until HEADER_END appears in
      your buffer. If recv() returns b"" before that, the peer closed early:
      return what you have, or None if you have nothing.

      Phase 2 — body. Split your buffer at the FIRST HEADER_END (bytes.partition
      is useful). Everything after it is body you have ALREADY read — do not
      throw it away. Call content_length() on the head, then keep recv()ing
      until you have that many body bytes. Stop early if recv() returns b"".

    A GET has Content-Length 0, so phase 2 does nothing. Good.

    Return the whole request — head + HEADER_END + body — so the caller can
    echo it verbatim.
    """
    raise NotImplementedError("TODO 2: read one full request")


# ---------------------------------------------------------------------------
# TODO 3 — build a response
# ---------------------------------------------------------------------------

def build_response(status: str, body: bytes,
                   content_type: str = "text/plain; charset=utf-8") -> bytes:
    """Assemble a complete HTTP response.

    `status` is a full status line without the version, e.g. "200 OK" or
    "404 Not Found". Produce:

        HTTP/1.1 200 OK\\r\\n
        Content-Type: text/plain; charset=utf-8\\r\\n
        Content-Length: <byte length of body>\\r\\n
        Connection: close\\r\\n
        \\r\\n
        <body>

    Content-Length must be the number of BYTES in `body`, not the number of
    characters in some string. len(b) on bytes is right; len('£') is 1 but it
    is 2 bytes in UTF-8. Get this wrong and clients truncate or hang — and we
    will POST you a '£' to check.
    """
    raise NotImplementedError("TODO 3: build the response")


# ---------------------------------------------------------------------------
# TODO 4 — route the request
# ---------------------------------------------------------------------------

def handle(request: bytes) -> bytes:
    """Turn a request into a response.

    Pull the method and target out of the request line (the first line, three
    space-separated fields: METHOD TARGET VERSION), then:

      GET /echo?a=1&b=2  ->  200, body is one 'key=value' line per query
                             parameter. urlsplit() gives you .path and .query;
                             parse_qsl() turns the query into pairs for you.
      POST /echo         ->  200, body is the request body, byte for byte.
      anything else      ->  404 Not Found, with a short text body.

    Note that '/echo' and '/echo?name=ada' must both route to /echo — compare
    the PATH, not the whole target.

    If the request line is malformed, return 400 Bad Request rather than
    raising. Use build_response() for all of these.
    """
    raise NotImplementedError("TODO 4: route on method and path")


# ---------------------------------------------------------------------------
# TODO 5 — the listening socket and accept loop
# ---------------------------------------------------------------------------

def serve(host: str, port: int, mark_crlf: bool, once: bool) -> None:
    """Open a listening socket and serve requests until interrupted.

    Steps (../sockets_demo.py shows every call):
      1. socket(AF_INET, SOCK_STREAM)
      2. setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)   <- do not skip this
      3. bind((host, port)), listen(5)
      4. print this line EXACTLY, check.py waits for it:
             print(f"listening on {host}:{port}", flush=True)
      5. loop forever:
           - accept() a connection
           - recv_request() it
           - TODO 6: print it to stdout (see below)
           - sendall(handle(request))
           - close that connection, keep the listener open
      6. break out of the loop after one request if `once` is true
         (check.py relies on this, and it is easy to get subtly wrong: make
         sure a client that connects and sends NOTHING still counts)

    Requirements:
      - Serve a SEQUENCE of clients. Exiting after one request fails.
      - Never crash. A truncated request, a missing or non-numeric
        Content-Length, or a client that connects and disconnects must not
        produce a traceback. Note that sendall() can itself raise OSError if
        the peer has already given up — guard it.
      - Catch KeyboardInterrupt so ctrl-c exits cleanly, and close the listener.

    TODO 6 — echo the request to stdout: print the request COMPLETE and
    UNMODIFIED, headers and body, using show(request, mark_crlf). Wrap it in
    marker lines so it is readable, and pass flush=True on every print or your
    output will appear in the wrong order when piped.
    """
    raise NotImplementedError("TODO 5 and 6: listening socket, accept loop, echo")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=HOST, help="default: %(default)s")
    ap.add_argument("--port", type=int, default=PORT, help="default: %(default)s")
    ap.add_argument("--show-crlf", action="store_true",
                    help="print \\r\\n literally so you can see HTTP's line endings")
    ap.add_argument("--once", action="store_true",
                    help="serve a single request then exit (check.py uses this)")
    args = ap.parse_args()

    try:
        serve(args.host, args.port, args.show_crlf, args.once)
    except OSError as exc:
        print(f"could not listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
