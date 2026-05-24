"""Walmart — best-effort. Walmart embeds its search results as JSON in a
``__NEXT_DATA__`` <script> tag. We parse that when present. Walmart blocks
bots aggressively (often a "Robot or human?" interstitial), so this adapter
frequently returns [] in automated environments — by design, never raising.
"""
from __future__ import annotations

import json

import httpx
from bs4 import BeautifulSoup

from ..models import Product
from .base import BROWSER_HEADERS, RetailerSource

SEARCH_URL = "https://www.walmart.com/search"


def _walk_items(node: object, out: list[dict]) -> None:
    """Depth-first hunt for product item dicts inside the NEXT_DATA blob."""
    if isinstance(node, dict):
        if "usItemId" in node and ("name" in node or "title" in node):
            out.append(node)
        for value in node.values():
            _walk_items(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_items(value, out)


def parse_next_data(html: str) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return []
    try:
        blob = json.loads(tag.string)
    except (json.JSONDecodeError, TypeError):
        return []

    raw_items: list[dict] = []
    _walk_items(blob, raw_items)

    out: list[Product] = []
    seen: set[str] = set()
    for item in raw_items:
        name = str(item.get("name") or item.get("title") or "")
        if "nee" not in name.lower().replace("-", "").replace(" ", ""):
            continue
        item_id = str(item.get("usItemId") or "")
        if item_id in seen:
            continue
        seen.add(item_id)

        canonical = item.get("canonicalUrl") or ""
        url = f"https://www.walmart.com{canonical}" if canonical.startswith("/") else (
            canonical or f"https://www.walmart.com/ip/{item_id}"
        )
        price = None
        price_info = item.get("priceInfo") or {}
        current = (price_info.get("currentPrice") or {}) if isinstance(price_info, dict) else {}
        if isinstance(current, dict):
            try:
                price = float(current.get("price"))
            except (TypeError, ValueError):
                price = None

        avail = str(item.get("availabilityStatusV2", {}).get("value")
                    if isinstance(item.get("availabilityStatusV2"), dict)
                    else item.get("availabilityStatus") or "").upper()
        in_stock = avail in ("", "IN_STOCK") or "IN_STOCK" in avail

        out.append(
            Product(
                name=name,
                store="walmart",
                url=url,
                in_stock=in_stock,
                price=price,
                image=item.get("imageInfo", {}).get("thumbnailUrl")
                if isinstance(item.get("imageInfo"), dict)
                else None,
                sku=item_id or None,
            )
        )
    return out


class WalmartSource(RetailerSource):
    name = "walmart"
    label = "Walmart"

    async def fetch(self, client: httpx.AsyncClient) -> list[Product]:
        resp = await client.get(
            SEARCH_URL,
            headers=BROWSER_HEADERS,
            params={"q": "needoh"},
            timeout=12.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_next_data(resp.text)
