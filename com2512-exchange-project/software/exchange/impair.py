"""Instructor-controlled network impairment, applied inside the server.

This is the software replacement for the hardware delay repeater, and it is
strictly better for teaching: it is calibrated by construction, it can be
changed mid-demonstration from the console, and it applies per protocol, so
the TCP desk and the UDP desk can be hurt differently at the same moment.

What it can do to a message on its way out:

    delay_ms    fixed one-way latency
    jitter_ms   uniform +/- variation on top of the delay
    loss        probability the message is dropped outright
    dup         probability the message is delivered twice
    reorder     probability the message is held back and released late,
                overtaking nothing but being overtaken by everything

The reason `reorder` is separate from `jitter` matters. Jitter varies delivery
time but a big enough jitter also reorders, which conflates two effects
students must tell apart: TCP hides reordering and pays for it in head-of-line
blocking, UDP exposes it and makes the application deal with it. Being able to
turn on reordering with zero added latency isolates that.

Impairment is seeded per gateway so a demonstration repeats. Change the seed
to get a different draw of the same distribution.

THE LAYER THIS RUNS AT, AND WHY IT CHANGES THE RULES
----------------------------------------------------
This impairer sits above the transport, not below it. That is fine for UDP,
where the application message and the datagram are the same thing. It is
WRONG for TCP unless it is told so, and getting this wrong produces a result
that looks completely plausible and teaches the opposite of the truth.

Drop an application message on a TCP gateway and you have not modelled a lossy
link. TCP would have retransmitted those bytes; the receiver would still have
got them, late. What you have actually modelled is TCP with its reliability
removed -- which makes TCP measure like UDP, and hides the entire distinction
the assignment exists to teach. It also corrupts the byte stream, because you
deleted the middle of a frame the receiver is still counting bytes for.

So a stream-mode Impairer converts loss into what loss actually costs a TCP
application: a retransmission timeout. It ignores duplication and reordering
outright, because TCP resequences and deduplicates below the application and
the application never sees them.

    Under a lossy link, UDP loses messages and TCP loses time.

That sentence is the whole comparison, and it only shows up in the numbers if
the impairment is applied at the right layer.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import asdict, dataclass


@dataclass
class Impairment:
    delay_ms: float = 0.0
    jitter_ms: float = 0.0
    loss: float = 0.0
    dup: float = 0.0
    reorder: float = 0.0
    reorder_ms: float = 60.0

    def is_clean(self) -> bool:
        return not (self.delay_ms or self.jitter_ms or self.loss
                    or self.dup or self.reorder)

    def describe(self) -> str:
        if self.is_clean():
            return "clean"
        bits = []
        if self.delay_ms:
            bits.append(f"{self.delay_ms:g}ms"
                        + (f"±{self.jitter_ms:g}" if self.jitter_ms else ""))
        elif self.jitter_ms:
            bits.append(f"±{self.jitter_ms:g}ms jitter")
        if self.loss:
            bits.append(f"{self.loss * 100:g}% loss")
        if self.dup:
            bits.append(f"{self.dup * 100:g}% dup")
        if self.reorder:
            bits.append(f"{self.reorder * 100:g}% reorder")
        return ", ".join(bits)


class Impairer:
    """Applies an Impairment to outbound sends. Counts what it did.

    stream=True marks a gateway whose transport is TCP (the TCP and REST
    gateways). See the module docstring: loss becomes a retransmission delay,
    duplication and reordering are not applied at all."""

    def __init__(self, name: str, seed: int = 1234, stream: bool = False,
                 rto_ms: float = 200.0) -> None:
        self.name = name
        self.stream = stream
        self.rto_ms = rto_ms
        self.cfg = Impairment()
        self.rng = random.Random(seed)
        self.sent = self.dropped = self.duplicated = self.reordered = 0
        self.retransmits = 0
        self._pending: set = set()      # asyncio drops tasks nobody references

    def stats(self) -> dict:
        return {"mode": "stream (TCP)" if self.stream else "datagram (UDP)",
                "sent": self.sent, "dropped": self.dropped,
                "duplicated": self.duplicated, "reordered": self.reordered,
                "retransmits": self.retransmits,
                "impairment": self.cfg.describe(), "config": asdict(self.cfg)}

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._pending.add(t)
        t.add_done_callback(self._pending.discard)

    async def send(self, deliver, data, await_delivery: bool = False) -> None:
        """Deliver `data` via `deliver(data)`, subject to impairment.

        `deliver` may be sync or async. Delayed delivery normally runs as a
        detached task so the caller is never blocked -- an exchange that stalls
        its matching engine to simulate latency is measuring the wrong thing.

        `await_delivery=True` waits instead. Request/response gateways need it:
        an HTTP handler that returns before its delayed response has been
        written will close the connection out from under it, and the client
        sees "remote end closed without response" rather than a slow reply."""
        c = self.cfg
        wait = c.delay_ms
        if c.jitter_ms:
            wait += self.rng.uniform(-c.jitter_ms, c.jitter_ms)
        copies = 1

        if self.stream:
            # TCP repairs loss, reordering and duplication below us. The only
            # application-visible cost of a lost segment is the retransmission
            # timeout, so charge that instead of deleting the message.
            tries = 0
            while c.loss and self.rng.random() < c.loss and tries < 4:
                tries += 1
            if tries:
                self.retransmits += tries
                wait += self.rto_ms * (2 ** tries - 1)     # exponential backoff
        else:
            if c.loss and self.rng.random() < c.loss:
                self.dropped += 1
                return
            if c.dup and self.rng.random() < c.dup:
                copies = 2
                self.duplicated += 1
            if c.reorder and self.rng.random() < c.reorder:
                wait += c.reorder_ms
                self.reordered += 1

        wait = max(0.0, wait) / 1000.0
        for _ in range(copies):
            self.sent += 1
            if wait <= 0:
                await _call(deliver, data)
            elif await_delivery:
                await _later(wait, deliver, data)
            else:
                self._spawn(_later(wait, deliver, data))


async def _call(deliver, data) -> None:
    r = deliver(data)
    if asyncio.iscoroutine(r):
        await r


async def _later(wait: float, deliver, data) -> None:
    try:
        await asyncio.sleep(wait)
        await _call(deliver, data)
    except (asyncio.CancelledError, ConnectionError, OSError):
        pass


PRESETS = {
    "clean":     Impairment(),
    "campus":    Impairment(delay_ms=8, jitter_ms=4, loss=0.001),
    "wifi-busy": Impairment(delay_ms=25, jitter_ms=20, loss=0.02, reorder=0.03),
    "satellite": Impairment(delay_ms=280, jitter_ms=15, loss=0.005),
    "leo":       Impairment(delay_ms=25, jitter_ms=10, loss=0.005),
    "lossy":     Impairment(delay_ms=5, loss=0.15),
    "brutal":    Impairment(delay_ms=120, jitter_ms=80, loss=0.10,
                            dup=0.05, reorder=0.15),
}
