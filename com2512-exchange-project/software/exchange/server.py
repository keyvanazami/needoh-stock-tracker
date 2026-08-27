"""XCHG: one matching engine, three gateways.

    TCP  :7001   length-prefixed binary frames, push market data
    UDP  :7002   the same frames as datagrams, unreliable, push market data
    HTTP :7003   JSON over REST, market data by polling

All three feed ONE order book, so a REST desk and a UDP desk trade against each
other for real. That is the whole design: the protocol is the variable, the
market is the constant, and at the end of the session the fills tell you which
choice was better.

A deliberate asymmetry, and the most important one to explain: the TCP and UDP
gateways PUSH market data, the REST gateway cannot. HTTP is request/response;
a REST client only learns the price changed by asking again. That is not a
limitation of this implementation, it is what REST is, and it is why the poll
interval a student picks becomes a visible strategy parameter -- poll fast and
you burn bandwidth and still lag, poll slow and you trade on stale prices.

Market data is UNICAST fan-out, not multicast, on purpose. Campus and
enterprise wireless almost always drop multicast and often block client-to-
client traffic entirely. Real exchanges multicast; we cannot rely on it here,
and pretending otherwise would break the class in week one. The gap between
those two facts is a good five minutes of lecture.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from . import messages as M
from .book import BUY, SELL, Book, Order
from .impair import Impairer, Impairment, PRESETS
from .wire import (Frame, StreamParser, T_CANCEL, T_HEARTBEAT, T_HELLO,
                   T_ORDER, T_QUOTE, T_TRADE, WireError, decode)

MD_HISTORY = 512


@dataclass
class Session:
    firm: int
    name: str
    transport: str                 # "tcp" | "udp" | "rest"
    peer: str
    msgs_in: int = 0
    msgs_out: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    orders: int = 0
    fills: int = 0
    rejects: int = 0
    joined: float = field(default_factory=time.time)

    def row(self) -> dict:
        d = {k: getattr(self, k) for k in
             ("firm", "name", "transport", "peer", "msgs_in", "msgs_out",
              "bytes_in", "bytes_out", "orders", "fills", "rejects")}
        d["bytes_per_order"] = round(self.bytes_in / self.orders, 1) if self.orders else 0
        d["up_s"] = round(time.time() - self.joined, 1)
        return d


class Exchange:
    """The venue: books, sessions, market-data sequencing and fan-out."""

    def __init__(self, tickers=("NDOH",)) -> None:
        self.books = {t: Book(t) for t in tickers}
        self.sessions: dict[int, Session] = {}
        self.md_seq = 0
        self.md_log: list[tuple[int, dict]] = []      # (seq, json-able message)
        self._subs: list = []                          # push callbacks
        self.started = time.time()

    # --- market data -------------------------------------------------------
    def subscribe(self, cb) -> None:
        self._subs.append(cb)

    def unsubscribe(self, cb) -> None:
        if cb in self._subs:
            self._subs.remove(cb)

    def _publish(self, frame: Frame, js: dict) -> None:
        self.md_seq += 1
        frame.seq = self.md_seq
        js = dict(js, seq=self.md_seq, t=round(time.time() - self.started, 4))
        self.md_log.append((self.md_seq, js))
        del self.md_log[:-MD_HISTORY]
        for cb in list(self._subs):
            try:
                cb(frame)
            except Exception:
                self.unsubscribe(cb)

    def publish_quote(self, ticker: str) -> None:
        b = self.books[ticker]
        bb, ba = b.best_bid(), b.best_ask()
        self._publish(
            M.enc_quote(ticker, bb, b.qty_at(BUY, bb), ba, b.qty_at(SELL, ba), 0),
            {"type": "QUOTE", "ticker": ticker, "bid": bb,
             "bid_qty": b.qty_at(BUY, bb), "ask": ba, "ask_qty": b.qty_at(SELL, ba)})

    def publish_trade(self, f) -> None:
        self._publish(
            M.enc_trade(f.ticker, f.px, f.qty, f.buy_firm, f.sell_firm, 0),
            {"type": "TRADE", "ticker": f.ticker, "px": f.px, "qty": f.qty,
             "buy_firm": f.buy_firm, "sell_firm": f.sell_firm})

    def md_since(self, seq: int, limit: int = 100) -> list[dict]:
        return [js for s, js in self.md_log if s > seq][:limit]

    # --- order entry -------------------------------------------------------
    def submit(self, sess: Session, d: dict) -> tuple[Frame, list]:
        """Apply one order. Returns (ack_or_reject_frame, fills)."""
        ticker = d.get("ticker") or "NDOH"
        book = self.books.get(ticker)
        if book is None:
            sess.rejects += 1
            return M.enc_reject(f"unknown ticker {ticker!r}", sess.firm), []
        try:
            o = Order(firm=sess.firm, side=int(d["side"]), px=int(d["px"]),
                      qty=int(d["qty"]), coid=int(d["coid"]), ticker=ticker)
            if o.side not in (BUY, SELL):
                raise ValueError("side must be 0 (buy) or 1 (sell)")
            fills = book.submit(o)
        except (KeyError, TypeError, ValueError) as e:
            sess.rejects += 1
            return M.enc_reject(str(e), sess.firm), []

        sess.orders += 1
        filled = sum(f.qty for f in fills)
        sess.fills += len(fills)
        for f in fills:
            other = f.sell_firm if f.buy_firm == sess.firm else f.buy_firm
            if other in self.sessions:
                self.sessions[other].fills += 1
            self.publish_trade(f)
        if fills:
            self.publish_quote(ticker)
        elif o.qty:
            self.publish_quote(ticker)

        status = (M.ACK_FILLED if filled and not o.qty
                  else M.ACK_PARTIAL if filled else M.ACK_OK)
        return M.enc_ack(o.coid, status, filled, o.qty, sess.firm), fills

    def cancel(self, sess: Session, d: dict) -> Frame:
        ticker = d.get("ticker") or "NDOH"
        book = self.books.get(ticker)
        if book is None:
            return M.enc_reject(f"unknown ticker {ticker!r}", sess.firm)
        ok = book.cancel(sess.firm, int(d["coid"]))
        if not ok:
            sess.rejects += 1
            return M.enc_reject(f"no resting order {d['coid']} for firm {sess.firm}",
                                sess.firm)
        self.publish_quote(ticker)
        return M.enc_ack(int(d["coid"]), M.ACK_CANCELLED, 0, 0, sess.firm)

    # --- bookkeeping -------------------------------------------------------
    def register(self, s: Session) -> None:
        self.sessions[s.firm] = s

    def stats(self) -> dict:
        return {
            "up_s": round(time.time() - self.started, 1),
            "md_seq": self.md_seq,
            "books": {t: b.snapshot() for t, b in self.books.items()},
            "depth": {t: b.depth() for t, b in self.books.items()},
            "sessions": [s.row() for s in self.sessions.values()],
        }


# ---------------------------------------------------------------------------
# TCP gateway
# ---------------------------------------------------------------------------
class TcpGateway:
    def __init__(self, ex: Exchange, imp: Impairer) -> None:
        self.ex, self.imp = ex, imp
        self.conns = 0

    async def handle(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        peer = "%s:%d" % writer.get_extra_info("peername")[:2]
        parser = StreamParser()
        sess: Session | None = None
        push = None
        self.conns += 1
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                for f in parser.feed(data):
                    if sess is None:
                        if f.type != T_HELLO:
                            writer.write(M.enc_reject("send HELLO first").encode())
                            await writer.drain()
                            return
                        h = M.decode_payload(f)
                        sess = Session(h["firm"], h["name"], "tcp", peer)
                        self.ex.register(sess)

                        def push(fr: Frame, w=writer, s=sess) -> None:
                            b = fr.encode()
                            s.msgs_out += 1
                            s.bytes_out += len(b)
                            w.write(b)
                        self.ex.subscribe(push)
                        await self.reply(sess, writer,
                                         Frame(T_HELLO, sess.firm, 0, 0, f.payload))
                        self.ex.publish_quote(next(iter(self.ex.books)))
                        continue
                    sess.msgs_in += 1
                    sess.bytes_in += len(f.payload) + 15
                    await self.dispatch(sess, writer, f)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError, OSError):
            pass
        except WireError:
            pass
        finally:
            self.conns -= 1
            if push:
                self.ex.unsubscribe(push)
            try:
                writer.close()
            except Exception:
                pass

    async def dispatch(self, sess, writer, f: Frame) -> None:
        if f.type == T_ORDER:
            ack, _ = self.ex.submit(sess, M.decode_payload(f))
            await self.reply(sess, writer, ack)
        elif f.type == T_CANCEL:
            await self.reply(sess, writer, self.ex.cancel(sess, M.decode_payload(f)))
        elif f.type == T_HEARTBEAT:
            await self.reply(sess, writer, Frame(T_HEARTBEAT, sess.firm))
        else:
            await self.reply(sess, writer,
                             M.enc_reject(f"unexpected {f.name} on order entry"))

    async def reply(self, sess, writer, frame: Frame) -> None:
        b = frame.encode()
        sess.msgs_out += 1
        sess.bytes_out += len(b)
        await self.imp.send(lambda d, w=writer: w.write(d), b)


# ---------------------------------------------------------------------------
# UDP gateway
# ---------------------------------------------------------------------------
class UdpGateway(asyncio.DatagramProtocol):
    """Order entry and market data over datagrams.

    Every reply is best-effort. A dropped ACK looks exactly like a dropped
    ORDER from the client's side, which is the entire lesson: the client
    cannot tell 'you never heard me' from 'I never heard you', and must pick
    a recovery policy that is safe under both. Resending an order that was
    actually filled is how you accidentally double your position."""

    def __init__(self, ex: Exchange, imp: Impairer) -> None:
        self.ex, self.imp = ex, imp
        self.transport = None
        self.peers: dict[str, tuple] = {}       # firm-key -> addr
        self.sessions: dict[tuple, Session] = {}

    def connection_made(self, transport) -> None:
        self.transport = transport

        def push(fr: Frame) -> None:
            b = fr.encode()
            for addr, s in list(self.sessions.items()):
                s.msgs_out += 1
                s.bytes_out += len(b)
                asyncio.create_task(
                    self.imp.send(lambda d, a=addr: self._send(d, a), b))
        self.ex.subscribe(push)
        self._push = push

    def _send(self, data: bytes, addr) -> None:
        if self.transport:
            try:
                self.transport.sendto(data, addr)
            except OSError:
                pass

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            f = decode(data)
        except WireError:
            return                       # a corrupt datagram is simply gone
        sess = self.sessions.get(addr)
        if f.type == T_HELLO:
            h = M.decode_payload(f)
            sess = Session(h["firm"], h["name"], "udp", "%s:%d" % addr[:2])
            self.sessions[addr] = sess
            self.ex.register(sess)
            asyncio.create_task(self.reply(sess, addr, Frame(T_HELLO, sess.firm, 0, 0, f.payload)))
            self.ex.publish_quote(next(iter(self.ex.books)))
            return
        if sess is None:
            return                       # unknown peer: no session, no reply
        sess.msgs_in += 1
        sess.bytes_in += len(data)
        try:
            if f.type == T_ORDER:
                ack, _ = self.ex.submit(sess, M.decode_payload(f))
                asyncio.create_task(self.reply(sess, addr, ack))
            elif f.type == T_CANCEL:
                asyncio.create_task(
                    self.reply(sess, addr, self.ex.cancel(sess, M.decode_payload(f))))
            elif f.type == T_HEARTBEAT:
                asyncio.create_task(self.reply(sess, addr, Frame(T_HEARTBEAT, sess.firm)))
        except WireError:
            pass

    async def reply(self, sess, addr, frame: Frame) -> None:
        b = frame.encode()
        sess.msgs_out += 1
        sess.bytes_out += len(b)
        await self.imp.send(lambda d, a=addr: self._send(d, a), b)


# ---------------------------------------------------------------------------
# HTTP / REST gateway
# ---------------------------------------------------------------------------
#   GET  /health                      liveness
#   GET  /quote?ticker=NDOH           top of book
#   GET  /book?ticker=NDOH            aggregated depth
#   GET  /md?since=<seq>              market data since a sequence number
#   POST /order    {ticker,side,px,qty,coid}     header X-Firm: <id>
#   POST /cancel   {ticker,coid}                 header X-Firm: <id>
#   GET  /stats                       every session, bytes and fills
#   GET  /admin/impair                current impairment on all gateways
#   POST /admin/impair {gateway, preset} or {gateway, delay_ms, loss, ...}
#
# Hand-rolled HTTP/1.1 rather than a framework, for two reasons: zero
# dependencies on eight different laptops, and students can read the request
# parser and see that HTTP is a text protocol with a length-delimited body --
# the same framing problem as the binary gateway, solved with Content-Length.
class HttpGateway:
    def __init__(self, ex: Exchange, imp: Impairer, gateways: dict) -> None:
        self.ex, self.imp, self.gateways = ex, imp, gateways
        self.requests = 0

    async def handle(self, reader, writer) -> None:
        peer = "%s:%d" % writer.get_extra_info("peername")[:2]
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                line, _, rest = head.partition(b"\r\n")
                parts = line.decode(errors="replace").split()
                if len(parts) < 2:
                    return
                method, target = parts[0], parts[1]
                headers = {}
                for h in rest.split(b"\r\n"):
                    k, _, v = h.partition(b":")
                    if k:
                        headers[k.decode(errors="replace").strip().lower()] = \
                            v.decode(errors="replace").strip()
                body = b""
                n = int(headers.get("content-length", 0) or 0)
                if n:
                    body = await reader.readexactly(n)
                self.requests += 1
                status, payload = self.route(method, target, headers, body, peer)
                await self.respond(writer, status, payload)
                if headers.get("connection", "").lower() == "close":
                    return
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def respond(self, writer, status: str, payload: dict) -> None:
        body = json.dumps(payload).encode()
        head = (f"HTTP/1.1 {status}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Cache-Control: no-store\r\n\r\n").encode()
        await self.imp.send(lambda d, w=writer: w.write(d), head + body,
                            await_delivery=True)
        try:
            await writer.drain()
        except (ConnectionError, OSError):
            pass

    # --- routing -----------------------------------------------------------
    def route(self, method, target, headers, body, peer):
        path, _, qs = target.partition("?")
        q = {}
        for kv in qs.split("&"):
            k, _, v = kv.partition("=")
            if k:
                q[k] = v
        try:
            if method == "GET":
                return self.get(path, q)
            if method == "POST":
                return self.post(path, q, headers, body, peer)
            return "405 Method Not Allowed", {"error": f"{method} not allowed"}
        except (KeyError, ValueError, TypeError) as e:
            return "400 Bad Request", {"error": str(e)}

    def get(self, path, q):
        ticker = q.get("ticker", next(iter(self.ex.books)))
        if path == "/health":
            return "200 OK", {"ok": True, "up_s": round(time.time() - self.ex.started, 1)}
        if path == "/quote":
            if ticker not in self.ex.books:
                return "404 Not Found", {"error": f"unknown ticker {ticker}"}
            return "200 OK", self.ex.books[ticker].snapshot()
        if path == "/book":
            if ticker not in self.ex.books:
                return "404 Not Found", {"error": f"unknown ticker {ticker}"}
            return "200 OK", self.ex.books[ticker].depth(int(q.get("levels", 5)))
        if path == "/md":
            since = int(q.get("since", 0))
            msgs = self.ex.md_since(since, int(q.get("limit", 100)))
            return "200 OK", {"seq": self.ex.md_seq, "messages": msgs}
        if path == "/stats":
            return "200 OK", self.ex.stats()
        if path == "/admin/impair":
            return "200 OK", {name: g.stats() for name, g in self.gateways.items()}
        return "404 Not Found", {"error": f"no route {path}"}

    def post(self, path, q, headers, body, peer):
        if path == "/admin/impair":
            return self.set_impair(json.loads(body or b"{}"))
        firm = int(headers.get("x-firm", 0))
        if not firm:
            return "401 Unauthorized", {"error": "set the X-Firm header to your firm id"}
        sess = self.ex.sessions.get(firm)
        if sess is None or sess.transport != "rest":
            sess = Session(firm, headers.get("x-name", f"firm{firm:04X}"), "rest", peer)
            self.ex.register(sess)
        sess.msgs_in += 1
        sess.bytes_in += len(body) + 180        # request line + typical headers
        d = json.loads(body or b"{}")
        if path == "/order":
            ack, fills = self.ex.submit(sess, d)
            out = M.decode_payload(ack)
            out["type"] = ack.name
            sess.msgs_out += 1
            status = "200 OK" if ack.name == "ACK" else "400 Bad Request"
            return status, out
        if path == "/cancel":
            ack = self.ex.cancel(sess, d)
            out = M.decode_payload(ack)
            out["type"] = ack.name
            sess.msgs_out += 1
            return ("200 OK" if ack.name == "ACK" else "404 Not Found"), out
        return "404 Not Found", {"error": f"no route {path}"}

    def set_impair(self, d):
        name = d.get("gateway", "all")
        targets = list(self.gateways) if name == "all" else [name]
        for t in targets:
            if t not in self.gateways:
                return "404 Not Found", {"error": f"unknown gateway {t}",
                                         "known": list(self.gateways) + ["all"]}
        if "preset" in d:
            if d["preset"] not in PRESETS:
                return "400 Bad Request", {"error": f"unknown preset {d['preset']}",
                                           "known": list(PRESETS)}
            for t in targets:
                self.gateways[t].cfg = Impairment(**vars(PRESETS[d["preset"]]))
        else:
            fields = {k: float(v) for k, v in d.items()
                      if k in Impairment.__dataclass_fields__}
            for t in targets:
                for k, v in fields.items():
                    setattr(self.gateways[t].cfg, k, v)
        return "200 OK", {t: {"impairment": self.gateways[t].cfg.describe(),
                              "config": vars(self.gateways[t].cfg)} for t in targets}
