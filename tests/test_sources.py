"""Parser tests for the retailer adapters and Instagram watcher, run against
small saved fixtures (no network). Run: python -m pytest tests/needoh."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from needoh_tracker.sources.facebook import parse_page as parse_facebook
from needoh_tracker.sources.instagram import parse_profile
from needoh_tracker.sources.schylling import parse_products as parse_schylling
from needoh_tracker.sources.target import parse_search as parse_target
from needoh_tracker.sources.walmart import parse_next_data as parse_walmart

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class SchyllingParserTest(unittest.TestCase):
    def test_parses_needoh_and_skips_others(self) -> None:
        products = parse_schylling(json.loads(_load("schylling_products.json")))
        names = {p.name for p in products}
        self.assertIn("NeeDoh Nice Cube", names)
        self.assertNotIn("Unrelated Plush Bear", names)

    def test_availability_from_variants(self) -> None:
        products = parse_schylling(json.loads(_load("schylling_products.json")))
        by_name = {p.name: p for p in products}
        self.assertTrue(by_name["NeeDoh Nice Cube"].in_stock)
        self.assertFalse(by_name["NeeDoh Dohnut"].in_stock)
        self.assertEqual(by_name["NeeDoh Nice Cube"].store, "schylling")


class TargetParserTest(unittest.TestCase):
    def test_parses_in_and_out_of_stock(self) -> None:
        products = parse_target(json.loads(_load("target_search.json")))
        by_sku = {p.sku: p for p in products}
        self.assertIn("12345", by_sku)
        self.assertTrue(by_sku["12345"].in_stock)
        self.assertFalse(by_sku["67890"].in_stock)
        self.assertEqual(by_sku["12345"].price, 9.99)

    def test_ambiguous_fulfillment_is_out_of_stock(self) -> None:
        # No explicit positive signal → conservative: treat as out of stock.
        products = parse_target(json.loads(_load("target_search.json")))
        by_sku = {p.sku: p for p in products}
        self.assertIn("55555", by_sku)
        self.assertFalse(by_sku["55555"].in_stock)

    def test_store_pickup_counts_as_in_stock(self) -> None:
        # Shipping OOS but pickup IN_STOCK → available.
        products = parse_target(json.loads(_load("target_search.json")))
        by_sku = {p.sku: p for p in products}
        self.assertIn("44444", by_sku)
        self.assertTrue(by_sku["44444"].in_stock)


class WalmartParserTest(unittest.TestCase):
    def test_parses_next_data(self) -> None:
        products = parse_walmart(_load("walmart_search.html"))
        self.assertTrue(any("nee" in p.name.lower().replace(" ", "") for p in products))


class InstagramParserTest(unittest.TestCase):
    def test_matches_restock_keyword(self) -> None:
        sightings = parse_profile("schylling", json.loads(_load("instagram_profile.json")))
        self.assertEqual(len(sightings), 1)
        self.assertEqual(sightings[0].matched_keyword, "back in stock")
        self.assertIn("/p/RESTOCK123/", sightings[0].post_url)


class FacebookParserTest(unittest.TestCase):
    def test_matches_restock_keywords(self) -> None:
        sightings = parse_facebook("schylling", _load("facebook_page.html"), store="schylling")
        captions = [s.caption for s in sightings]
        # og:description ("back in stock") + the "restock just dropped" post.
        self.assertTrue(any("back in stock" in c.lower() for c in captions))
        self.assertTrue(any("restock just dropped" in c.lower() for c in captions))
        # Non-matching lines (store hours, welcome) are excluded.
        self.assertFalse(any("store hours" in c.lower() for c in captions))
        self.assertTrue(all(s.platform == "facebook" for s in sightings))
        self.assertTrue(all(s.store == "schylling" for s in sightings))

    def test_distinct_sightings_dedupe_by_caption(self) -> None:
        sightings = parse_facebook("schylling", _load("facebook_page.html"))
        keys = {s.key for s in sightings}
        self.assertEqual(len(keys), len(sightings))


if __name__ == "__main__":
    unittest.main()
