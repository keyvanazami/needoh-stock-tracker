"""Tests for restock dedupe logic in TrackerStore — the heart of "only notify
on a real restock". Run with: python -m pytest tests/needoh  (or unittest)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from needoh_tracker.models import Product, RestockSighting
from needoh_tracker.store import TrackerStore


def _product(sku: str, in_stock: bool, store: str = "target") -> Product:
    return Product(
        name="NeeDoh Nice Cube",
        store=store,
        url=f"https://example.com/{sku}",
        in_stock=in_stock,
        sku=sku,
    )


class RestockDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = TrackerStore(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_seen_in_stock_is_a_restock(self) -> None:
        restocked = self.store.apply_products([_product("A1", True)])
        self.assertEqual([p.sku for p in restocked], ["A1"])

    def test_first_seen_out_of_stock_is_not_a_restock(self) -> None:
        restocked = self.store.apply_products([_product("A1", False)])
        self.assertEqual(restocked, [])

    def test_out_to_in_flip_is_a_restock(self) -> None:
        self.store.apply_products([_product("A1", False)])
        restocked = self.store.apply_products([_product("A1", True)])
        self.assertEqual([p.sku for p in restocked], ["A1"])

    def test_staying_in_stock_does_not_renotify(self) -> None:
        self.store.apply_products([_product("A1", True)])  # first restock
        restocked = self.store.apply_products([_product("A1", True)])  # still in stock
        self.assertEqual(restocked, [])

    def test_in_to_out_then_in_renotifies(self) -> None:
        self.store.apply_products([_product("A1", True)])
        self.store.apply_products([_product("A1", False)])
        restocked = self.store.apply_products([_product("A1", True)])
        self.assertEqual([p.sku for p in restocked], ["A1"])

    def test_products_persist_across_instances(self) -> None:
        self.store.apply_products([_product("A1", True)])
        reopened = TrackerStore(Path(self._tmp.name))
        keys = [p["sku"] for p in reopened.list_products()]
        self.assertIn("A1", keys)
        # Re-seeing it in stock should NOT be a fresh restock after reload.
        restocked = reopened.apply_products([_product("A1", True)])
        self.assertEqual(restocked, [])


class SightingDedupeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = TrackerStore(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_only_new_sightings_returned(self) -> None:
        s = RestockSighting(account="schylling", post_url="https://ig/p/abc", caption="restock!", matched_keyword="restock")
        first = self.store.add_sightings([s])
        self.assertEqual(len(first), 1)
        again = self.store.add_sightings([s])
        self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
