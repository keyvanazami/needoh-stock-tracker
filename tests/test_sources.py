"""Parser tests for the retailer adapters and Instagram watcher, run against
small saved fixtures (no network). Run: python -m pytest tests/needoh."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
