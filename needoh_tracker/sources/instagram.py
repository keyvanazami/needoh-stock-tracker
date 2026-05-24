"""Instagram restock watcher.

Instagram's official Graph API is gated behind app review and a Business
account, so for personal use we hit the public profile JSON endpoint
(``?__a=1&__d=dis``) that the web client uses. Instagram heavily rate-limits
and often requires login for this, so it frequently returns nothing in
automated environments — the watcher degrades to [] and never raises.

For each watched account we scan recent post captions for restock keywords
(see ``config.RESTOCK_KEYWORDS``) and emit a ``RestockSighting`` per match.
"""
from __future__ import annotations

import logging

import httpx

from ..config import RESTOCK_KEYWORDS
from ..models import RestockSighting
from .base import BROWSER_HEADERS

log = logging.getLogger(__name__)

PROFILE_URL = "https://www.instagram.com/{user}/"
POST_URL = "https://www.instagram.com/p/{shortcode}/"


def _match_keyword(caption: str) -> str | None:
    low = caption.lower()
    for kw in RESTOCK_KEYWORDS:
        if kw in low:
            return kw
    return None


def parse_profile(account: str, payload: object) -> list[RestockSighting]:
    """Extract restock sightings from a profile JSON body.

    Handles the common shape:
    data.user.edge_owner_to_timeline_media.edges[].node{shortcode, edge_media_to_caption}.
    """
    if not isinstance(payload, dict):
        return []
    user = (((payload.get("data") or {}).get("user")) or payload.get("graphql", {}).get("user")
            if isinstance(payload.get("graphql"), dict) else (payload.get("data") or {}).get("user"))
    if not isinstance(user, dict):
        return []
    media = user.get("edge_owner_to_timeline_media") or {}
    edges = media.get("edges") if isinstance(media, dict) else None
    if not isinstance(edges, list):
        return []

    out: list[RestockSighting] = []
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            continue
        caption = ""
        cap_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
        if cap_edges and isinstance(cap_edges[0], dict):
            caption = str((cap_edges[0].get("node") or {}).get("text") or "")
        kw = _match_keyword(caption)
        if not kw:
            continue
        shortcode = node.get("shortcode") or ""
        out.append(
            RestockSighting(
                account=account,
                post_url=POST_URL.format(shortcode=shortcode) if shortcode else PROFILE_URL.format(user=account),
                caption=caption[:500],
                matched_keyword=kw,
            )
        )
    return out


async def fetch_account(client: httpx.AsyncClient, account: str) -> list[RestockSighting]:
    """Fetch one account's recent posts. Never raises."""
    try:
        resp = await client.get(
            PROFILE_URL.format(user=account),
            headers={**BROWSER_HEADERS, "X-IG-App-ID": "936619743392459"},
            params={"__a": "1", "__d": "dis"},
            timeout=10.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_profile(account, resp.json())
    except Exception as err:  # noqa: BLE001
        log.warning("[instagram:%s] fetch failed: %s", account, err)
        return []
