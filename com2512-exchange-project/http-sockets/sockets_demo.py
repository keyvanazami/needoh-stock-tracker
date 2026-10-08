#!/usr/bin/env python3
"""The socket calls you need, and nothing else.

This is plain TCP — there is no HTTP anywhere in this file. It exists to show
you the six calls that open a socket and move bytes over it. Writing HTTP on
top of these is your job in server.py and client.py.

    terminal 1:  python3 sockets_demo.py listen
    terminal 2:  python3 sockets_demo.py send "hello sockets"

THE LISTENING SIDE (a server)        THE CONNECTING SIDE (a client)
    socket()   make the socket           socket()    make the socket
    bind()     claim host:port           connect()   reach out to host:port
    listen()   start queueing            sendall()   write bytes
    accept()   take one connection       recv()      read bytes
    recv()     read bytes                close()
    sendall()  write bytes
    close()
"""

import socket
import sys

HOST = "127.0.0.1"
PORT = 8080
RECV_SIZE = 4096


def listen_side() -> None:
    """Accept one connection, read everything sent, write a reply back."""

    # AF_INET = IPv4, SOCK_STREAM = TCP. That pair is what "a TCP socket" means.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Without this, restarting within ~60s of a previous run fails with
    # "Address already in use" — the old connection is still in TIME_WAIT.
    # You WILL hit this during the lab. This line is the fix.
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    listener.bind((HOST, PORT))   # claim the port
    listener.listen(5)            # 5 = how many pending connections may queue
    print(f"listening on {HOST}:{PORT}", flush=True)

    # accept() blocks until someone connects, then returns a NEW socket for that
    # one conversation plus the peer's address. The listener keeps listening.
    conn, peer = listener.accept()
    print(f"connection from {peer[0]}:{peer[1]}", flush=True)

    with conn:
        # THE CENTRAL LESSON: recv() is not "receive a message". It returns
        # whatever bytes have arrived so far — maybe all of them, maybe three of
        # them. So you loop. Here we loop until recv() returns b"", which means
        # the peer closed its end (EOF).
        received = b""
        while True:
            chunk = conn.recv(RECV_SIZE)
            if not chunk:
                break
            received += chunk
            print(f"  recv() returned {len(chunk)} bytes", flush=True)

        print(f"got {len(received)} bytes total: {received!r}", flush=True)

        # sendall() keeps writing until every byte is handed to the kernel.
        # Plain send() may write only part of your buffer and return a count —
        # forgetting that is a classic bug. Prefer sendall().
        conn.sendall(b"ack: " + received)

    listener.close()
    print("closed", flush=True)


def send_side(message: str) -> None:
    """Connect, write a message, read the reply until the peer closes."""

    # create_connection() does socket() + connect() for you and handles
    # IPv4/IPv6. Long-hand, it is:
    #     sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #     sock.connect((HOST, PORT))
    with socket.create_connection((HOST, PORT), timeout=5) as sock:
        sock.sendall(message.encode("utf-8"))

        # We are done writing, so close our write half. This sends FIN, which is
        # what makes the other side's recv() return b"" and break its loop.
        #
        # Worth sitting with: here, "end of message" means "end of connection".
        # HTTP cannot work that way — it sends many requests down one connection,
        # so it needs its own way to say where a message stops. That is exactly
        # what Content-Length is for, and it is the problem you solve next.
        sock.shutdown(socket.SHUT_WR)

        reply = b""
        while True:
            chunk = sock.recv(RECV_SIZE)
            if not chunk:
                break
            reply += chunk

    print(f"reply: {reply!r}")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("listen", "send"):
        print(__doc__)
        return 2
    if sys.argv[1] == "listen":
        listen_side()
    else:
        send_side(sys.argv[2] if len(sys.argv) > 2 else "hello sockets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
