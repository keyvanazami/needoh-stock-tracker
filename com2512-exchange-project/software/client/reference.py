"""Reference clients: the same trading logic over TCP, UDP and REST.

This is what you hand students AFTER they have written their own, or hand them
now as the thing to beat. All three expose the same three methods --
`order`, `cancel`, `poll` -- so `bench.py` can drive any of them and the only
variable is the transport.

Read these three classes side by side. The trading logic is identical and
about ten lines; everything else is the cost of the transport, and the amount
of code each one needs is itself a result worth discussing.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from exchange import messages as M
from exchange.wire import (Frame, StreamParser, T_ACK, T_HEARTBEAT, T_HELLO,
                           T_QUOTE, T_REJECT, T_TRADE, WireError, decode)


class TcpClient:
    """Reliable, ordered, framed. The stream parser is the whole difficulty."""

    def __init__(self, host, port, firm, name="ref-tcp", timeout=5.0):
        self.firm, self.name = firm, name
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.parser = StreamParser()
        self.quotes, self.trades, self.acks, self.rejects = 0, 0, 0, 0
        self.last_quote = None
        self.send(M.enc_hello(firm, name))

    def send(self, frame: Frame) -> None:
        self.sock.sendall(frame.encode())

    def order(self, ticker, side, px, qty, coid):
        self.send(M.enc_order(ticker, side, px, qty, coid, firm=self.firm))

    def cancel(self, ticker, coid):
        self.send(M.enc_cancel(ticker, coid, firm=self.firm))

    def poll(self, timeout=0.0):
        """Drain whatever has arrived. Returns decoded messages."""
        self.sock.settimeout(timeout)
        out = []
        try:
            data = self.sock.recv(65536)
            if not data:
                return out
            for f in self.parser.feed(data):
                out.append(self._on(f))
        except (socket.timeout, BlockingIOError):
            pass
        return [o for o in out if o]

    def _on(self, f: Frame):
        if f.type == T_QUOTE:
            self.quotes += 1
            self.last_quote = M.dec_quote(f)
            return self.last_quote | {"type": "QUOTE"}
        if f.type == T_TRADE:
            self.trades += 1
            return M.dec_trade(f) | {"type": "TRADE"}
        if f.type == T_ACK:
            self.acks += 1
            return M.dec_ack(f) | {"type": "ACK"}
        if f.type == T_REJECT:
            self.rejects += 1
            return M.dec_reject(f) | {"type": "REJECT"}
        return None

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class UdpClient:
    """Unreliable and unordered. Everything TCP did for you is now yours.

    Note what is NOT here: no retransmission, no sequence-gap recovery, no
    duplicate suppression. That is the assignment. This client will lose fills
    the moment the instructor turns on loss, and it should."""

    def __init__(self, host, port, firm, name="ref-udp", timeout=5.0):
        self.firm, self.name, self.addr = firm, name, (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.quotes, self.trades, self.acks, self.rejects = 0, 0, 0, 0
        self.bad, self.gaps, self.last_seq = 0, 0, 0
        self.last_quote = None
        self.send(M.enc_hello(firm, name))

    def send(self, frame: Frame) -> None:
        self.sock.sendto(frame.encode(), self.addr)

    def order(self, ticker, side, px, qty, coid):
        self.send(M.enc_order(ticker, side, px, qty, coid, firm=self.firm))

    def cancel(self, ticker, coid):
        self.send(M.enc_cancel(ticker, coid, firm=self.firm))

    def poll(self, timeout=0.0):
        # Wait up to `timeout` for the FIRST datagram, then drain whatever else
        # is already queued without blocking. Blocking for the full timeout
        # after the data has arrived would add the timeout to every measured
        # round trip -- an artifact of the client, reported as a property of
        # the protocol.
        self.sock.settimeout(timeout)
        out = []
        while True:
            try:
                data, _ = self.sock.recvfrom(65536)
                self.sock.settimeout(0)
            except (socket.timeout, BlockingIOError):
                return out
            except OSError:
                return out
            try:
                f = decode(data)
            except WireError:
                self.bad += 1
                continue
            if f.type in (T_QUOTE, T_TRADE):
                if self.last_seq and f.seq > self.last_seq + 1:
                    self.gaps += f.seq - self.last_seq - 1
                self.last_seq = max(self.last_seq, f.seq)
            m = self._on(f)
            if m:
                out.append(m)

    _on = TcpClient._on

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class RestClient:
    """Request/response only. There is no push, so market data must be polled.

    `poll()` here really does make a network round trip every call, which is
    why the bench reports its message count and byte count separately: a REST
    client that keeps up with the market is spending most of its bytes asking
    whether anything happened."""

    def __init__(self, host, port, firm, name="ref-rest", timeout=5.0):
        self.base = f"http://{host}:{port}"
        self.firm, self.name, self.timeout = firm, name, timeout
        self.quotes, self.trades, self.acks, self.rejects = 0, 0, 0, 0
        self.md_seq, self.http_requests, self.http_bytes = 0, 0, 0
        self.last_quote = None
        # Start from the CURRENT sequence, not 0: otherwise the first poll
        # replays every message still in the server's history buffer and the
        # client counts other people's trades as its own market data.
        try:
            self.md_seq = self._req("GET", "/md?since=0&limit=0").get("seq", 0)
        except OSError:
            self.md_seq = 0

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("X-Firm", str(self.firm))
        req.add_header("X-Name", self.name)
        if data:
            req.add_header("Content-Type", "application/json")
        self.http_requests += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                self.http_bytes += len(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            self.http_bytes += len(raw)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"error": e.reason}

    def order(self, ticker, side, px, qty, coid):
        r = self._req("POST", "/order",
                      {"ticker": ticker, "side": side, "px": px, "qty": qty, "coid": coid})
        self.acks += r.get("type") == "ACK"
        self.rejects += r.get("type") == "REJECT"
        return r

    def cancel(self, ticker, coid):
        return self._req("POST", "/cancel", {"ticker": ticker, "coid": coid})

    def poll(self, timeout=0.0):
        r = self._req("GET", f"/md?since={self.md_seq}")
        out = []
        for m in r.get("messages", []):
            self.md_seq = max(self.md_seq, m.get("seq", 0))
            if m["type"] == "QUOTE":
                self.quotes += 1
                self.last_quote = m
            elif m["type"] == "TRADE":
                self.trades += 1
            out.append(m)
        return out

    def close(self):
        pass


CLIENTS = {"tcp": TcpClient, "udp": UdpClient, "rest": RestClient}
