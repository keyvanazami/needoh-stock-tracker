#!/usr/bin/env python3
"""A TCP echo server that speaks just enough HTTP to be legible to a browser.

Nothing here is an HTTP library. We open a listening socket, read bytes, print
them, and write bytes back. Every header you see on the wire is one this file
put there, which is the entire point of the exercise.

    python3 echo_server.py                 # listen on 127.0.0.1:8080
    python3 echo_server.py --show-crlf     # make line endings visible
    python3 echo_server.py --host 0.0.0.0  # reachable from another machine
"""

import argparse
import socket
import sys

RECV_SIZE = 4096
CRLF = b"\r\n"
HEADER_END = CRLF + CRLF  # a blank line ends the header block (RFC 9112 2.1)


def content_length(head: bytes) -> int:
    """Pull Content-Length out of a header block. 0 when absent or malformed.

    Field names are case-insensitive, so we lowercase before comparing. We skip
    head.split(CRLF)[0] because that is the request line, not a header.
    """
    for line in head.split(CRLF)[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            try:
                return int(value.strip())
            except ValueError:
                return 0
    return 0


def recv_request(conn: socket.socket) -> bytes | None:
    """Read exactly one HTTP request off the connection.

    This is the part students most often get wrong. recv() is not a message
    receive -- it hands back whatever has arrived, which may be half a header
    or two requests glued together. So we read in a loop until we have seen the
    blank line, then read exactly Content-Length more bytes for the body.

    Returns None if the peer closed without sending anything.
    """
    buf = b""
    while HEADER_END not in buf:
        chunk = conn.recv(RECV_SIZE)
        if not chunk:  # peer closed mid-request (or sent nothing at all)
            return buf or None
        buf += chunk

    head, _, body = buf.partition(HEADER_END)
    want = content_length(head)

    # A GET has want == 0 and this loop never runs. A POST usually arrives in
    # the same segment as its headers, but it is not guaranteed to.
    while len(body) < want:
        chunk = conn.recv(min(RECV_SIZE, want - len(body)))
        if not chunk:
            break
        body += chunk

    return head + HEADER_END + body


def build_response(request: bytes) -> bytes:
    """200 OK whose body is the request we just received -- hence 'echo'.

    Content-Length must be the byte count, not the character count. Get this
    wrong and the client either hangs waiting for bytes that never come or
    truncates the body.
    """
    body = request
    head = CRLF.join([
        b"HTTP/1.1 200 OK",
        b"Content-Type: text/plain; charset=utf-8",
        b"Content-Length: " + str(len(body)).encode("ascii"),
        b"Connection: close",
        b"Server: com2512-echo/1.0",
    ])
    return head + HEADER_END + body


def show(data: bytes, mark_crlf: bool) -> str:
    """Render request bytes for a human. Invalid UTF-8 is replaced, not fatal."""
    text = data.decode("utf-8", errors="replace")
    if mark_crlf:
        text = text.replace("\r\n", "\\r\\n\n")
    return text


def serve(host: str, port: int, mark_crlf: bool, once: bool) -> None:
    # AF_INET = IPv4, SOCK_STREAM = TCP. That pair is what "a TCP socket" means.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Without SO_REUSEADDR, restarting the server inside ~60s of a previous run
    # fails with "Address already in use" because the old connection is still
    # in TIME_WAIT. You will hit this during the lab; this line is the fix.
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    listener.bind((host, port))   # claim the port
    listener.listen(5)            # backlog: queued connections awaiting accept()
    print(f"listening on http://{host}:{port}/  (ctrl-c to stop)", flush=True)

    try:
        while True:
            # accept() blocks until a client connects, then returns a NEW socket
            # for that one conversation. The listener keeps listening.
            conn, peer = listener.accept()
            with conn:
                request = recv_request(conn)
                if request is None:
                    print(f"--- {peer[0]}:{peer[1]} connected and sent nothing", flush=True)
                else:
                    print(f"--- {len(request)} bytes from {peer[0]}:{peer[1]} ---", flush=True)
                    print(show(request, mark_crlf), flush=True)
                    print("--- end of request ---\n", flush=True)

                    # The peer may already be gone (it gave up waiting, or sent a
                    # request we could not frame). Report it rather than crashing.
                    try:
                        conn.sendall(build_response(request))
                    except OSError as exc:
                        print(f"could not reply to {peer[0]}:{peer[1]}: {exc}", flush=True)
            if once:
                break
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        listener.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default: %(default)s; use 0.0.0.0 to accept "
                         "connections from other machines)")
    ap.add_argument("--port", type=int, default=8080, help="default: %(default)s")
    ap.add_argument("--show-crlf", action="store_true",
                    help="print \\r\\n literally so you can see HTTP's line endings")
    ap.add_argument("--once", action="store_true",
                    help="serve a single request then exit (used by selftest.py)")
    args = ap.parse_args()

    try:
        serve(args.host, args.port, args.show_crlf, args.once)
    except OSError as exc:
        print(f"could not listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
