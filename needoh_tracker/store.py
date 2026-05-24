"""Durable JSON-on-disk state: the product watchlist (with in-stock history),
Instagram sightings, web-push subscriptions, and the call log.

Pattern follows ``python_backend/lesson_store.py``: a single JSON file is
loaded on start and rewritten atomically on each mutation. Volume is tiny
(a handful of products), so this is plenty.

The watchlist is the source of truth for restock detection: each product
remembers its last known ``in_stock`` flag, so a poll can tell a fresh
restock (``False -> True`` or first-seen-in-stock) apart from a product that
has merely stayed in stock since the previous cycle.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .models import CallRecord, Product, RestockSighting

log = logging.getLogger(__name__)

_MAX_SIGHTINGS = 100
_MAX_CALLS = 100


class TrackerStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir
        self._path = data_dir / "state.json"
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "products": {},  # key -> product dict (latest snapshot)
            "sightings": {},  # key -> sighting dict
            "subscriptions": [],  # web-push subscription dicts
            "calls": [],  # most-recent-first call records
        }
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        try:
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    self._state.update(loaded)
        except Exception as err:  # noqa: BLE001
            log.warning("[store] failed to load %s: %s", self._path, err)

    def _flush(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2)
            os.replace(tmp, self._path)
        except Exception as err:  # noqa: BLE001
            log.warning("[store] failed to flush %s: %s", self._path, err)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ---- products / restock detection ----

    def apply_products(self, products: list[Product]) -> list[Product]:
        """Merge a fresh batch of listings into the watchlist.

        Returns the products that just became available — i.e. the ones we
        should notify about. A product counts as a restock when it is newly
        seen while in stock, or when its stored flag was False and is now True.
        """
        restocked: list[Product] = []
        with self._lock:
            existing = self._state["products"]
            for product in products:
                prev = existing.get(product.key)
                was_in_stock = bool(prev.get("in_stock")) if prev else False
                if product.in_stock and not was_in_stock:
                    restocked.append(product)
                existing[product.key] = product.to_dict()
            self._flush()
        return restocked

    def list_products(self) -> list[dict]:
        with self._lock:
            items = list(self._state["products"].values())
        items.sort(key=lambda p: (not p.get("in_stock"), p.get("store", ""), p.get("name", "")))
        return items

    # ---- instagram sightings ----

    def add_sightings(self, sightings: list[RestockSighting]) -> list[RestockSighting]:
        """Store new sightings; return only the ones not seen before."""
        fresh: list[RestockSighting] = []
        with self._lock:
            store = self._state["sightings"]
            for sighting in sightings:
                if sighting.key not in store:
                    store[sighting.key] = sighting.to_dict()
                    fresh.append(sighting)
            # Trim to the newest N by seen_at.
            if len(store) > _MAX_SIGHTINGS:
                ordered = sorted(store.items(), key=lambda kv: kv[1].get("seen_at", ""))
                for key, _ in ordered[: len(store) - _MAX_SIGHTINGS]:
                    store.pop(key, None)
            self._flush()
        return fresh

    def list_sightings(self) -> list[dict]:
        with self._lock:
            items = list(self._state["sightings"].values())
        items.sort(key=lambda s: s.get("seen_at", ""), reverse=True)
        return items

    # ---- web-push subscriptions ----

    def add_subscription(self, subscription: dict) -> None:
        endpoint = subscription.get("endpoint")
        if not endpoint:
            return
        with self._lock:
            subs = self._state["subscriptions"]
            if not any(s.get("endpoint") == endpoint for s in subs):
                subs.append(subscription)
                self._flush()

    def remove_subscription(self, endpoint: str) -> None:
        with self._lock:
            subs = self._state["subscriptions"]
            kept = [s for s in subs if s.get("endpoint") != endpoint]
            if len(kept) != len(subs):
                self._state["subscriptions"] = kept
                self._flush()

    def list_subscriptions(self) -> list[dict]:
        with self._lock:
            return list(self._state["subscriptions"])

    # ---- call log ----

    def add_call(self, record: CallRecord) -> None:
        with self._lock:
            calls = self._state["calls"]
            calls.insert(0, record.to_dict())
            del calls[_MAX_CALLS:]
            self._flush()

    def update_call_result(self, sid: str, result: str, status: str | None = None) -> bool:
        with self._lock:
            for call in self._state["calls"]:
                if call.get("sid") == sid:
                    call["result"] = result
                    if status:
                        call["status"] = status
                    self._flush()
                    return True
        return False

    def list_calls(self) -> list[dict]:
        with self._lock:
            return list(self._state["calls"])
