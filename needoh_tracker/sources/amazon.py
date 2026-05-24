"""Amazon — best-effort search-page scrape. Amazon serves bot traffic a CAPTCHA
or a stripped page very often, so this adapter is the least reliable and will
usually return [] in automated environments. Parsing targets the standard
search result card markup; when Amazon changes layout or blocks us, we log and
return [] (never raise). High-frequency scraping violates Amazon's ToS — the
default 10-minute poll keeps this polite and personal-use only.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from ..models import Product
from .base import BROWSER_HEADERS, RetailerSource

SEARCH_URL = "https://www.amazon.com/s"


def parse_search_html(html: str) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Product] = []
    seen: set[str] = set()

    for card in soup.select("div[data-asin]"):
        asin = card.get("data-asin") or ""
        if not asin or asin in seen:
            continue

        title_el = card.select_one("h2 span") or card.select_one("h2 a span")
        name = title_el.get_text(strip=True) if title_el else ""
        if "nee" not in name.lower().replace("-", "").replace(" ", ""):
            continue
        seen.add(asin)

        link_el = card.select_one("h2 a") or card.select_one("a.a-link-normal")
        href = link_el.get("href") if link_el else None
        url = f"https://www.amazon.com{href}" if href and href.startswith("/") else (
            href or f"https://www.amazon.com/dp/{asin}"
        )

        price = None
        whole = card.select_one("span.a-price span.a-offscreen")
        if whole:
            m = re.search(r"[\d,]+\.?\d*", whole.get_text())
            if m:
                try:
                    price = float(m.group(0).replace(",", ""))
                except ValueError:
                    price = None

        img_el = card.select_one("img.s-image")
        image = img_el.get("src") if img_el else None

        # Amazon search cards rarely carry a clean stock flag; treat presence
        # of a price/buy affordance as in stock, and an explicit unavailable
        # string as OOS.
        text = card.get_text(" ", strip=True).lower()
        in_stock = price is not None and "currently unavailable" not in text

        out.append(
            Product(
                name=name,
                store="amazon",
                url=url.split("/ref=")[0],
                in_stock=in_stock,
                price=price,
                image=image,
                sku=asin,
            )
        )
    return out


class AmazonSource(RetailerSource):
    name = "amazon"
    label = "Amazon"

    async def fetch(self, client: httpx.AsyncClient) -> list[Product]:
        resp = await client.get(
            SEARCH_URL,
            headers=BROWSER_HEADERS,
            params={"k": "needoh"},
            timeout=12.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_search_html(resp.text)
