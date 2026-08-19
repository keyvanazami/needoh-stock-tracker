"""Network Emulator Proxy: sits between client and server and abuses the link.

Injects, per datagram and independently in each direction:
  * loss        (drop outright)
  * corruption  (flip a random bit -> the Internet checksum must catch it)
  * delay       (uniform jitter, which naturally causes reordering)
  * duplication (deliver twice)

Deterministic under a fixed seed so a failing run can be replayed.
"""

from __future__ import annotations

import asyncio
import random


class LinkProfile:
    def __init__(self, loss=0.0, corrupt=0.0, dup=0.0, delay=(0.0, 0.0), seed=1234):
        self.loss = loss
        self.corrupt = corrupt
        self.dup = dup
        self.delay = delay
        self.rng = random.Random(seed)

    def __str__(self):
        return (
            f"loss={self.loss:.0%} corrupt={self.corrupt:.0%} dup={self.dup:.0%} "
            f"delay={self.delay[0]*1000:.0f}-{self.delay[1]*1000:.0f}ms"
        )


class EmulatorStats:
    def __init__(self):
        self.passed = self.lost = self.corrupted = self.duped = 0

    def __str__(self):
        return (
            f"forwarded={self.passed} dropped={self.lost} "
            f"corrupted={self.corrupted} duplicated={self.duped}"
        )


class NetemProxy:
    """UDP relay: client <-> proxy <-> server, mangling both directions."""

    def __init__(self, server_addr, profile: LinkProfile):
        self.server_addr = server_addr
        self.profile = profile
        self.stats = EmulatorStats()
        self.client_addr = None
        self.transport = None

    class _Proto(asyncio.DatagramProtocol):
        def __init__(self, outer):
            self.outer = outer

        def connection_made(self, transport):
            self.outer.transport = transport

        def datagram_received(self, data, addr):
            o = self.outer
            if addr == o.server_addr:
                dst = o.client_addr
            else:
                o.client_addr = addr
                dst = o.server_addr
            if dst is not None:
                asyncio.create_task(o._relay(data, dst))

    @classmethod
    async def create(cls, server_addr, profile, local=("127.0.0.1", 0)):
        self = cls(server_addr, profile)
        loop = asyncio.get_event_loop()
        await loop.create_datagram_endpoint(lambda: cls._Proto(self), local_addr=local)
        return self

    @property
    def sockname(self):
        return self.transport.get_extra_info("sockname")

    def _sendto(self, data, dst) -> bool:
        if self.transport is None or self.transport.is_closing():
            return False
        self.transport.sendto(data, dst)
        return True

    async def _relay(self, data: bytes, dst):
        p = self.profile
        if p.rng.random() < p.loss:
            self.stats.lost += 1
            return
        if p.rng.random() < p.corrupt:
            b = bytearray(data)
            i = p.rng.randrange(len(b))
            b[i] ^= 1 << p.rng.randrange(8)
            data = bytes(b)
            self.stats.corrupted += 1
        lo, hi = p.delay
        if hi > 0:
            await asyncio.sleep(p.rng.uniform(lo, hi))
        if not self._sendto(data, dst):
            return
        self.stats.passed += 1
        if p.rng.random() < p.dup:
            self.stats.duped += 1
            await asyncio.sleep(p.rng.uniform(0, hi or 0.001))
            self._sendto(data, dst)

    def close(self):
        if self.transport:
            self.transport.close()
