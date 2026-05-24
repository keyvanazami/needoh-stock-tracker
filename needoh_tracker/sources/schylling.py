"""Schylling — the NeeDoh manufacturer. Their storefront is Shopify, which
exposes a public ``/products.json`` feed (no key needed). This is the most
reliable signal: structured JSON with title, price, image, and per-variant
``available`` flags.
"""
from __future__ import annotations

import httpx

from ..models import Product
from .base import BROWSER_HEADERS, RetailerSource

# Shopify caps page_size at 250; NeeDoh is one product family so one page is plenty.
PRODUCTS_JSON = "https://schylling.com/products.json"
PRODUCT_BASE = "https://schylling.com/products/"


def parse_products(payload: object) -> list[Product]:
    """Pull NeeDoh listings out of a Shopify products.json body."""
    if not isinstance(payload, dict):
        return []
    raw_products = payload.get("products")
    if not isinstance(raw_products, list):
        return []

    out: list[Product] = []
    for item in raw_products:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        product_type = str(item.get("product_type") or "")
        tags = item.get("tags") or []
        haystack = " ".join([title, product_type, " ".join(tags) if isinstance(tags, list) else str(tags)]).lower()
        if "nee" not in haystack.replace("-", "").replace(" ", ""):
            # Match "needoh" / "nee doh" / "nee-doh" after stripping separators.
            continue

        handle = item.get("handle") or ""
        url = f"{PRODUCT_BASE}{handle}" if handle else "https://schylling.com"

        variants = item.get("variants") or []
        in_stock = any(
            isinstance(v, dict) and v.get("available") for v in variants
        )
        price = None
        if variants and isinstance(variants[0], dict):
            try:
                price = float(variants[0].get("price"))
            except (TypeError, ValueError):
                price = None

        image = None
        images = item.get("images") or []
        if images and isinstance(images[0], dict):
            image = images[0].get("src")

        out.append(
            Product(
                name=title or "NeeDoh",
                store="schylling",
                url=url,
                in_stock=bool(in_stock),
                price=price,
                image=image,
                sku=str(item.get("id")) if item.get("id") is not None else None,
            )
        )
    return out


class SchyllingSource(RetailerSource):
    name = "schylling"
    label = "Schylling (official)"

    async def fetch(self, client: httpx.AsyncClient) -> list[Product]:
        resp = await client.get(
            PRODUCTS_JSON,
            headers=BROWSER_HEADERS,
            params={"limit": 250},
            timeout=10.0,
        )
        resp.raise_for_status()
        return parse_products(resp.json())
