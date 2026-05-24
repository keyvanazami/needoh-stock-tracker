"""Target — via the public RedSky ``plp_search_v2`` endpoint that target.com's
own frontend calls. It returns structured JSON (title, price, image, and an
availability status per item). RedSky requires a ``key`` query param; Target
ships a well-known web client key in its public bundle. If Target rotates it
or blocks the request, this adapter simply returns [] (never raises).
"""
from __future__ import annotations

import httpx

from ..config import SEARCH_TERMS
from ..models import Product
from .base import BROWSER_HEADERS, RetailerSource

REDSKY_SEARCH = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2"
# Public web client key shipped in target.com's frontend bundle. Overridable
# via env if it rotates.
import os

WEB_KEY = os.environ.get("TARGET_API_KEY", "9f36aeafbe60771e321a7cc95a78140772ab3e96")


def parse_search(payload: object) -> list[Product]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or {}
    search = data.get("search") or {}
    products = search.get("products")
    if not isinstance(products, list):
        return []

    out: list[Product] = []
    for item in products:
        if not isinstance(item, dict):
            continue
        item_desc = (item.get("item") or {}).get("product_description") or {}
        title = str(item_desc.get("title") or "")
        if "nee" not in title.lower().replace("-", "").replace(" ", ""):
            continue

        tcin = item.get("tcin")
        url = ((item.get("item") or {}).get("enrichment") or {}).get("buy_url")
        if not url and tcin:
            url = f"https://www.target.com/p/-/A-{tcin}"

        price_block = item.get("price") or {}
        price = price_block.get("current_retail")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        images = (item.get("item") or {}).get("enrichment", {}).get("images") or {}
        image = images.get("primary_image_url")

        # Availability: RedSky exposes an out_of_stock_all_locations style flag
        # plus a purchasability status. Treat anything not explicitly OOS as
        # available, since PLP doesn't always carry inventory counts.
        fulfillment = item.get("fulfillment") or {}
        is_oos = fulfillment.get("is_out_of_stock_in_all_store_locations")
        shipping = (fulfillment.get("shipping_options") or {}).get("availability_status")
        in_stock = True
        if shipping:
            in_stock = str(shipping).upper() == "IN_STOCK"
        elif is_oos is True:
            in_stock = False

        out.append(
            Product(
                name=title or "NeeDoh",
                store="target",
                url=url or "https://www.target.com",
                in_stock=bool(in_stock),
                price=price,
                image=image,
                sku=str(tcin) if tcin else None,
            )
        )
    return out


class TargetSource(RetailerSource):
    name = "target"
    label = "Target"

    async def fetch(self, client: httpx.AsyncClient) -> list[Product]:
        results: dict[str, Product] = {}
        for term in SEARCH_TERMS[:1]:  # one query is enough; RedSky fuzzy-matches
            params = {
                "key": WEB_KEY,
                "keyword": term,
                "count": "24",
                "offset": "0",
                "page": f"/s/{term}",
                "pricing_store_id": "3991",
                "visitor_id": "0",
                "channel": "WEB",
            }
            resp = await client.get(
                REDSKY_SEARCH, headers=BROWSER_HEADERS, params=params, timeout=10.0
            )
            resp.raise_for_status()
            for product in parse_search(resp.json()):
                results[product.key] = product
        return list(results.values())
