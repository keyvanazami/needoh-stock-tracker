"""Phase 4: virtual CSMA/CD multiple-access emulation over a shared medium.

Models a half-duplex broadcast bus:
  * carrier sense   - a station defers while the bus shows carrier (1-persistent)
  * collision detect - two stations whose transmissions overlap inside the
                       propagation window both abort and jam
  * binary exponential backoff - wait k * SLOT where k is uniform in
                       [0, 2^min(attempts,10) - 1], giving up after 16 tries

Also provides a token-passing alternative so the two disciplines can be
compared on the same offered load, which is the actual point of the exercise.
"""

from __future__ import annotations

import asyncio
import random

SLOT = 0.001  # 1 ms slot time
PROP = 0.0002  # propagation window in which a collision can still occur
IFG = 0.0001  # interframe gap: the bus must be released before re-contending
MAX_ATTEMPTS = 16


class MediumStats:
    def __init__(self):
        self.transmitted = 0
        self.collisions = 0
        self.aborted = 0
        self.backoff_slots = 0
        self.busy_time = 0.0

    def __str__(self):
        return (
            f"frames={self.transmitted} collisions={self.collisions} "
            f"give-ups={self.aborted} backoff-slots={self.backoff_slots}"
        )


class SharedMedium:
    """A single collision domain. Stations must win it before they can send."""

    def __init__(self, seed=7):
        self.senders: set[int] = set()
        self.stats = MediumStats()
        self.rng = random.Random(seed)
        self.delivered: list[tuple[int, bytes]] = []
        self.listeners: dict[int, callable] = {}
        # Carrier is only *sensed* once a transmission has propagated (PROP
        # after it starts). Stations that sense idle inside that window all
        # commit and collide -- that window is the whole reason CSMA/CD needs
        # collision detection. Two modelling traps live here:
        #   1. polling carrier on a timer staggers wakeups, so deferred
        #      stations never rush the bus simultaneously;
        #   2. re-checking `busy` after waking turns the rush into an orderly
        #      handoff. 1-persistent means: you sensed idle, you transmit.
        # Either one silently yields a collision-free (and wrong) model.
        self._carrier = False
        self._idle_ev = asyncio.Event()
        self._idle_ev.set()

    def _set_carrier(self, on: bool):
        self._carrier = on
        if on:
            self._idle_ev.clear()
        else:
            self._idle_ev.set()

    def attach(self, station_id: int, cb):
        self.listeners[station_id] = cb

    @property
    def busy(self) -> bool:
        return self._carrier

    async def transmit(self, station_id: int, data: bytes, duration: float = SLOT):
        attempts = 0
        while attempts < MAX_ATTEMPTS:
            # --- carrier sense (1-persistent): defer, then commit on idle ---
            if self._carrier:
                await self._idle_ev.wait()

            # --- transmit; anyone else who sensed idle within PROP collides ---
            self.senders.add(station_id)
            await asyncio.sleep(PROP)

            if len(self.senders) > 1:
                # --- collision detected: jam, abort, back off ---
                self.stats.collisions += 1
                self.senders.discard(station_id)
                if not self.senders:
                    self._set_carrier(False)
                attempts += 1
                k = self.rng.randrange(0, 2 ** min(attempts, 10))
                self.stats.backoff_slots += k
                await asyncio.sleep(k * SLOT)
                continue

            # --- we own the bus: assert carrier for the rest of the frame ---
            self._set_carrier(True)
            await asyncio.sleep(max(duration - PROP, 0))
            self.senders.discard(station_id)
            self._set_carrier(False)
            self.stats.transmitted += 1
            self.stats.busy_time += duration
            for sid, cb in self.listeners.items():
                if sid != station_id:
                    cb(station_id, data)
            # Interframe gap. Without it the station that just finished
            # re-enters carrier sense in the same tick and re-seizes an idle
            # bus before any deferred station is scheduled, which starves the
            # others and hides every collision.
            await asyncio.sleep(IFG)
            return True

        self.stats.aborted += 1
        return False


class TokenRing:
    """Token-passing alternative: collision-free by construction."""

    def __init__(self, station_ids):
        self.order = list(station_ids)
        self.holder = 0
        self.stats = MediumStats()
        self._cv = asyncio.Condition()

    async def transmit(self, station_id: int, data: bytes, duration: float = SLOT):
        async with self._cv:
            while self.order[self.holder] != station_id:
                await self._cv.wait()
            await asyncio.sleep(duration)
            self.stats.transmitted += 1
            self.stats.busy_time += duration
            self.holder = (self.holder + 1) % len(self.order)
            self._cv.notify_all()
        return True

    async def pass_token(self):
        """Advance the token so idle stations don't stall the ring."""
        async with self._cv:
            self.holder = (self.holder + 1) % len(self.order)
            self._cv.notify_all()
