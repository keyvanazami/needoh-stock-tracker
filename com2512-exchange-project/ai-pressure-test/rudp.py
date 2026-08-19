"""Phase 2: Reliable Data Transfer over an unreliable datagram channel (Go-Back-N).

Segment layout (13-byte header, big-endian):

   SEQ(4) | ACK(4) | FLAGS(1) | LEN(2) | CKSUM(2) | payload[LEN]

* SEQ counts *segments*, not bytes (textbook GBN).
* ACK carries "next expected seq" (cumulative), so ACK=0 means nothing yet.
* CKSUM is the 16-bit one's-complement Internet checksum over the whole
  segment with the CKSUM field zeroed. Corrupt segments are silently dropped,
  which is what forces the retransmit path to actually work.
* Sender keeps ONE timer, for the base of the window (per RFC/textbook GBN).
  On timeout every unacked segment in [base, nextseq) is resent.

The transport is a byte stream: `write()` appends to a send queue that the
pump slices into MSS-sized segments; the receiver appends in-order payloads to
a buffer that `readexactly()` waits on. Out-of-order segments are discarded and
a duplicate ACK is returned, exactly as GBN prescribes.
"""

from __future__ import annotations

import asyncio
import struct

HDR = "!IIBHH"
HDR_LEN = struct.calcsize(HDR)  # 13
assert HDR_LEN == 13

F_DATA = 0x01
F_ACK = 0x02
F_FIN = 0x08

MSS = 512
WINDOW = 8
RTO = 0.20


def inet_checksum(data: bytes) -> int:
    """16-bit one's complement sum, folded, complemented (RFC 1071)."""
    if len(data) & 1:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def pack_seg(seq: int, ack: int, flags: int, payload: bytes = b"") -> bytes:
    head = struct.pack(HDR, seq & 0xFFFFFFFF, ack & 0xFFFFFFFF, flags, len(payload), 0)
    ck = inet_checksum(head + payload)
    return struct.pack(HDR, seq & 0xFFFFFFFF, ack & 0xFFFFFFFF, flags, len(payload), ck) + payload


def unpack_seg(data: bytes):
    """Returns (seq, ack, flags, payload) or None if corrupt/truncated."""
    if len(data) < HDR_LEN:
        return None
    seq, ack, flags, ln, ck = struct.unpack_from(HDR, data, 0)
    payload = data[HDR_LEN : HDR_LEN + ln]
    if len(payload) != ln:
        return None
    zeroed = struct.pack(HDR, seq, ack, flags, ln, 0) + payload
    if inet_checksum(zeroed) != ck:
        return None  # corrupt -> drop, GBN will retransmit
    return seq, ack, flags, payload


class Channel:
    """Datagram channel abstraction: real UDP, emulator, or overlay mesh."""

    async def send(self, data: bytes):
        raise NotImplementedError

    def set_receiver(self, cb):
        self._cb = cb


class Stats:
    def __init__(self):
        self.sent = self.resent = self.acked = self.dropped_corrupt = 0
        self.out_of_order = self.timeouts = self.dup_acks = 0

    def __str__(self):
        return (
            f"sent={self.sent} resent={self.resent} timeouts={self.timeouts} "
            f"corrupt-drops={self.dropped_corrupt} ooo-drops={self.out_of_order} "
            f"dup-acks={self.dup_acks}"
        )


class RudpConn:
    def __init__(self, channel: Channel, name="rudp", window=WINDOW, rto=RTO, cc=False):
        self.ch = channel
        self.name = name
        self.window = window
        self.rto = rto
        self.stats = Stats()

        # Phase 4: TCP-style AIMD. cwnd in segments; slow start until ssthresh,
        # then additive increase (+1 MSS per RTT); multiplicative decrease on loss.
        self.cc = cc
        self.cwnd = 1.0
        self.ssthresh = float(window)
        self.cwnd_trace: list[tuple[float, float, str]] = []

        self.sendq = bytearray()
        self.inflight: dict[int, bytes] = {}
        self.base = 0
        self.nextseq = 0

        self.rcv_expected = 0
        self.rcvbuf = bytearray()
        self.closed = False

        self._data_ev = asyncio.Event()
        self._space_ev = asyncio.Event()
        self._space_ev.set()
        self._work_ev = asyncio.Event()
        self._timer: asyncio.TimerHandle | None = None
        self._loop = asyncio.get_event_loop()
        channel.set_receiver(self._on_datagram)
        self._pump = asyncio.create_task(self._pump_loop())

    # ---------- timer ----------
    def _start_timer(self):
        self._stop_timer()
        self._timer = self._loop.call_later(self.rto, self._on_timeout)

    def _stop_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _on_timeout(self):
        self._timer = None
        if self.base == self.nextseq:
            return
        self.stats.timeouts += 1
        if self.cc:
            # multiplicative decrease: loss is the congestion signal
            self.ssthresh = max(self.cwnd / 2.0, 1.0)
            self.cwnd = 1.0
            self._trace("loss")
        for s in range(self.base, self.nextseq):
            seg = self.inflight.get(s)
            if seg is not None:
                self.stats.resent += 1
                asyncio.create_task(self.ch.send(seg))
        self._start_timer()

    # ---------- receive path ----------
    def _on_datagram(self, data: bytes):
        got = unpack_seg(data)
        if got is None:
            self.stats.dropped_corrupt += 1
            # corrupt: drop silently, and nudge the peer with a dup ACK
            asyncio.create_task(self.ch.send(pack_seg(0, self.rcv_expected, F_ACK)))
            return
        seq, ack, flags, payload = got

        if flags & F_ACK:
            if ack > self.base:
                newly = ack - self.base
                for s in range(self.base, min(ack, self.nextseq)):
                    self.inflight.pop(s, None)
                self.base = ack
                if self.cc:
                    for _ in range(newly):
                        if self.cwnd < self.ssthresh:
                            self.cwnd += 1.0  # slow start: exponential
                        else:
                            self.cwnd += 1.0 / self.cwnd  # AI: +1 per RTT
                    self._trace("ack")
                self.stats.acked = ack
                if self.base == self.nextseq:
                    self._stop_timer()
                else:
                    self._start_timer()
                self._space_ev.set()
                self._work_ev.set()
            else:
                self.stats.dup_acks += 1

        if flags & (F_DATA | F_FIN):
            if seq == self.rcv_expected:
                if payload:
                    self.rcvbuf += payload
                    self._data_ev.set()
                self.rcv_expected += 1
                if flags & F_FIN:
                    self.closed = True
                    self._data_ev.set()
            else:
                self.stats.out_of_order += 1
            # cumulative ACK of everything received in order so far
            asyncio.create_task(self.ch.send(pack_seg(0, self.rcv_expected, F_ACK)))

    def _trace(self, why):
        self.cwnd_trace.append((self._loop.time(), self.cwnd, why))

    def _eff_window(self) -> int:
        if not self.cc:
            return self.window
        return max(1, min(self.window, int(self.cwnd)))

    # ---------- send path ----------
    async def _pump_loop(self):
        try:
            while True:
                await self._work_ev.wait()
                self._work_ev.clear()
                while self.sendq and self.nextseq < self.base + self._eff_window():
                    chunk = bytes(self.sendq[:MSS])
                    del self.sendq[: len(chunk)]
                    seg = pack_seg(self.nextseq, self.rcv_expected, F_DATA, chunk)
                    self.inflight[self.nextseq] = seg
                    if self.base == self.nextseq:
                        self._start_timer()
                    self.nextseq += 1
                    self.stats.sent += 1
                    await self.ch.send(seg)
                if self.nextseq >= self.base + self._eff_window():
                    self._space_ev.clear()
        except asyncio.CancelledError:
            pass

    def write(self, data: bytes):
        self.sendq += data
        self._work_ev.set()

    async def drain(self):
        # block while the window is full so a fast app can't outrun the window
        while self.sendq or self.nextseq >= self.base + self._eff_window():
            self._work_ev.set()
            await asyncio.sleep(0.001)

    async def flush(self, timeout=10.0):
        """Wait until everything written has been cumulatively ACKed."""
        end = self._loop.time() + timeout
        while (self.sendq or self.base < self.nextseq) and self._loop.time() < end:
            self._work_ev.set()
            await asyncio.sleep(0.005)
        return self.base >= self.nextseq and not self.sendq

    # ---------- stream-ish reader API (matches asyncio.StreamReader use) ----------
    async def readexactly(self, n: int) -> bytes:
        while len(self.rcvbuf) < n:
            if self.closed and len(self.rcvbuf) < n:
                raise asyncio.IncompleteReadError(bytes(self.rcvbuf), n)
            self._data_ev.clear()
            await self._data_ev.wait()
        out = bytes(self.rcvbuf[:n])
        del self.rcvbuf[:n]
        return out

    def close(self):
        self._stop_timer()
        self._pump.cancel()


class UdpChannel(Channel):
    """Real UDP socket bound locally, sending to a fixed peer."""

    def __init__(self):
        self._cb = lambda d: None
        self.transport = None
        self.peer = None

    class _Proto(asyncio.DatagramProtocol):
        def __init__(self, outer):
            self.outer = outer

        def datagram_received(self, data, addr):
            if self.outer.peer is None:
                self.outer.peer = addr
            self.outer._cb(data)

        def error_received(self, exc):
            pass

    @classmethod
    async def create(cls, local=("127.0.0.1", 0), peer=None):
        self = cls()
        loop = asyncio.get_event_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: cls._Proto(self), local_addr=local
        )
        self.peer = peer
        return self

    @property
    def sockname(self):
        return self.transport.get_extra_info("sockname")

    async def send(self, data: bytes):
        if self.peer is not None:
            self.transport.sendto(data, self.peer)

    def close(self):
        if self.transport:
            self.transport.close()
