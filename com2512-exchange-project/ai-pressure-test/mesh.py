"""Phase 3: application-layer overlay mesh with decentralized Distance-Vector routing.

Overlay packet (6-byte header, big-endian):
    TYPE(1) | SRC(1) | DST(1) | TTL(1) | LEN(2) | payload[LEN]

TYPE: 1=HELLO (neighbour liveness), 2=DV (distance vector), 3=DATA (R-UDP segment).

Each node runs Bellman-Ford over the vectors its live neighbours advertise:
    D(x, dest) = min over live neighbours n of ( c(x,n) + D(n, dest) )
Split horizon with poisoned reverse suppresses the two-node count-to-infinity
loop. Neighbours are declared down when HELLOs stop arriving, which drops their
vector out of the minimisation and reroutes traffic on the next recompute.
"""

from __future__ import annotations

import asyncio
import struct
import time

HDR = "!BBBBH"
HDR_LEN = struct.calcsize(HDR)  # 6

P_HELLO = 1
P_DV = 2
P_DATA = 3

INF = 16  # "infinity" for DV, RIP-style
HELLO_EVERY = 0.10
DEAD_AFTER = 0.45
DV_EVERY = 0.15
DEFAULT_TTL = 16


def pack(ptype, src, dst, payload=b"", ttl=DEFAULT_TTL):
    return struct.pack(HDR, ptype, src, dst, ttl, len(payload)) + payload


def unpack(data):
    if len(data) < HDR_LEN:
        return None
    ptype, src, dst, ttl, ln = struct.unpack_from(HDR, data, 0)
    payload = data[HDR_LEN : HDR_LEN + ln]
    if len(payload) != ln:
        return None
    return ptype, src, dst, ttl, payload


def encode_dv(vec: dict[int, int]) -> bytes:
    out = bytearray()
    for dest, cost in vec.items():
        out += struct.pack("!BB", dest, min(cost, INF))
    return bytes(out)


def decode_dv(data: bytes) -> dict[int, int]:
    return {data[i]: data[i + 1] for i in range(0, len(data) - 1, 2)}


class RoutingNode:
    """One student-built overlay router. Also acts as a host endpoint."""

    def __init__(self, node_id: int, name: str = ""):
        self.id = node_id
        self.name = name or f"n{node_id}"
        self.links: dict[int, tuple] = {}  # neighbour id -> udp addr
        self.link_cost: dict[int, int] = {}
        self.last_hello: dict[int, float] = {}
        self.neighbour_dv: dict[int, dict[int, int]] = {}
        self.table: dict[int, tuple[int, int]] = {self.id: (self.id, 0)}
        self.transport = None
        self.up = True
        self.on_data = None  # callback(src, payload)
        self.forwarded = 0
        self.dropped_noroute = 0
        self.recomputes = 0
        self._tasks: list[asyncio.Task] = []
        self._route_log: list[tuple[float, dict]] = []

    # ---------- plumbing ----------
    class _Proto(asyncio.DatagramProtocol):
        def __init__(self, outer):
            self.outer = outer

        def connection_made(self, transport):
            self.outer.transport = transport

        def datagram_received(self, data, addr):
            self.outer._on_packet(data)

        def error_received(self, exc):
            pass

    @classmethod
    async def create(cls, node_id, name=""):
        self = cls(node_id, name)
        loop = asyncio.get_event_loop()
        await loop.create_datagram_endpoint(
            lambda: cls._Proto(self), local_addr=("127.0.0.1", 0)
        )
        return self

    @property
    def sockname(self):
        return self.transport.get_extra_info("sockname")

    def add_link(self, neighbour_id: int, addr, cost: int = 1):
        self.links[neighbour_id] = addr
        self.link_cost[neighbour_id] = cost

    def start(self):
        self._tasks = [
            asyncio.create_task(self._hello_loop()),
            asyncio.create_task(self._dv_loop()),
        ]

    def stop(self):
        """Hard failure: the node stops sending, forwarding, and answering."""
        self.up = False
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    def close(self):
        self.stop()
        if self.transport:
            self.transport.close()

    def _send_raw(self, data, addr):
        if self.transport and not self.transport.is_closing():
            self.transport.sendto(data, addr)

    # ---------- control plane ----------
    async def _hello_loop(self):
        while True:
            for n, addr in self.links.items():
                self._send_raw(pack(P_HELLO, self.id, n), addr)
            await asyncio.sleep(HELLO_EVERY)

    async def _dv_loop(self):
        while True:
            self._expire_neighbours()
            self._recompute()
            self._advertise()
            await asyncio.sleep(DV_EVERY)

    def _expire_neighbours(self):
        now = time.monotonic()
        for n in list(self.last_hello):
            if now - self.last_hello[n] > DEAD_AFTER:
                del self.last_hello[n]
                self.neighbour_dv.pop(n, None)

    def _alive(self, n):
        return n in self.last_hello and (time.monotonic() - self.last_hello[n]) <= DEAD_AFTER

    def _recompute(self):
        new = {self.id: (self.id, 0)}
        dests = {self.id}
        for n in self.links:
            if self._alive(n):
                dests.add(n)
                dests.update(self.neighbour_dv.get(n, {}))
        for d in dests:
            if d == self.id:
                continue
            best, hop = INF, None
            for n in self.links:
                if not self._alive(n):
                    continue
                c = self.link_cost[n]
                dn = 0 if d == n else self.neighbour_dv.get(n, {}).get(d, INF)
                if c + dn < best:
                    best, hop = c + dn, n
            if hop is not None and best < INF:
                new[d] = (hop, best)
        if new != self.table:
            self.table = new
            self.recomputes += 1
            self._route_log.append((time.monotonic(), dict(new)))

    def _advertise(self):
        for n, addr in self.links.items():
            if not self._alive(n):
                continue
            vec = {}
            for dest, (hop, cost) in self.table.items():
                # split horizon with poisoned reverse
                vec[dest] = INF if (hop == n and dest != n) else cost
            self._send_raw(pack(P_DV, self.id, n, encode_dv(vec)), addr)

    # ---------- data plane ----------
    def _on_packet(self, data):
        if not self.up:
            return
        got = unpack(data)
        if not got:
            return
        ptype, src, dst, ttl, payload = got

        if ptype == P_HELLO:
            self.last_hello[src] = time.monotonic()
            return
        if ptype == P_DV:
            self.last_hello[src] = time.monotonic()
            self.neighbour_dv[src] = decode_dv(payload)
            return
        if ptype == P_DATA:
            if dst == self.id:
                if self.on_data:
                    self.on_data(src, payload)
                return
            if ttl <= 1:
                self.dropped_noroute += 1
                return
            self._forward(src, dst, ttl - 1, payload)

    def _forward(self, src, dst, ttl, payload):
        route = self.table.get(dst)
        if not route:
            self.dropped_noroute += 1
            return
        hop, _cost = route
        addr = self.links.get(hop)
        if not addr:
            self.dropped_noroute += 1
            return
        self.forwarded += 1
        self._send_raw(pack(P_DATA, src, dst, payload, ttl), addr)

    def send_data(self, dst: int, payload: bytes):
        if dst == self.id:
            return
        self._forward(self.id, dst, DEFAULT_TTL, payload)

    def route_str(self):
        parts = [f"{d}->via{h}({c})" for d, (h, c) in sorted(self.table.items()) if d != self.id]
        return " ".join(parts) or "(no routes)"


class MeshChannel:
    """rudp.Channel over the overlay: R-UDP segments ride as DATA packets."""

    def __init__(self, node: RoutingNode, peer_id: int):
        self.node = node
        self.peer_id = peer_id
        self._cb = lambda d: None
        node.on_data = self._deliver

    def _deliver(self, src, payload):
        self._cb(payload)

    def set_receiver(self, cb):
        self._cb = cb

    async def send(self, data: bytes):
        self.node.send_data(self.peer_id, data)


async def wait_for_convergence(nodes, dests, timeout=5.0):
    """Block until every node has a route to every dest (or timeout)."""
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if all(all(d in n.table for d in dests if d != n.id) for n in nodes if n.up):
            return True
        await asyncio.sleep(0.05)
    return False
