"""Facebook page restock watcher.

Facebook's Graph API needs an app, a Page token, and review for anything
useful, so for personal use we fetch a public page's HTML (and its
``og:description`` meta) and scan the visible text for restock keywords (see
``config.RESTOCK_KEYWORDS``). Facebook blocks bots aggressively and usually
gates content behind login, so this frequently returns nothing in automated
environments — the watcher degrades to [] and never raises.

Unlike Instagram we can't reliably resolve individual post permalinks, so
sightings link back to the page and dedupe on caption text (see
``RestockSighting.key``).
"""
from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from ..config import RESTOCK_KEYWORDS
from ..models import RestockSighting
from .base import BROWSER_HEADERS

log = logging.getLogger(__name__)

PAGE_URL = "https://www.facebook.com/{page}"
# mbasic serves lighter, less script-heavy HTML that's easier to read text from.
MBASIC_URL = "https://mbasic.facebook.com/{page}"
_MAX_MATCHES = 20


def _match_keyword(text: str) -> str | None:
    low = text.lower()
    for kw in RESTOCK_KEYWORDS:
        if kw in low:
            return kw
    return None


def parse_page(account: str, html: str, store: str | None = None) -> list[RestockSighting]:
    """Extract restock sightings from a page's HTML.

    Scans the ``og:description`` meta plus each line of visible body text for a
    restock keyword, emitting one sighting per distinct matched line.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    candidates: list[str] = []
    meta = soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        candidates.append(str(meta["content"]))
    body_text = soup.get_text(separator="\n")
    candidates.extend(line.strip() for line in body_text.splitlines())

    page_url = PAGE_URL.format(page=account)
    out: list[RestockSighting] = []
    seen: set[str] = set()
    for text in candidates:
        if not text or text in seen:
            continue
        kw = _match_keyword(text)
        if not kw:
            continue
        seen.add(text)
        out.append(
            RestockSighting(
                account=account,
                post_url=page_url,
                caption=text[:500],
                matched_keyword=kw,
                platform="facebook",
                store=store,
            )
        )
        if len(out) >= _MAX_MATCHES:
            break
    return out


async def fetch_page(
    client: httpx.AsyncClient, account: str, store: str | None = None
) -> list[RestockSighting]:
    """Fetch one page's recent content. Never raises."""
    try:
        resp = await client.get(
            MBASIC_URL.format(page=account),
            headers=BROWSER_HEADERS,
            timeout=10.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_page(account, resp.text, store)
    except Exception as err:  # noqa: BLE001
        log.warning("[facebook:%s] fetch failed: %s", account, err)
        return []
