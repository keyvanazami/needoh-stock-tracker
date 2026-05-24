"""Adapter contract for retailer stock checks.

Like ``python_backend/research.py``, adapters must **never raise** in caller
code: network errors, blocks, and shape changes are logged and turned into an
empty list. This keeps one flaky retailer from breaking a whole poll cycle.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from ..models import Product

log = logging.getLogger(__name__)

# A realistic desktop User-Agent. Many retailers serve empty/blocked bodies to
# obvious bots; this is best-effort and stays within polite, low-frequency use.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class RetailerSource(ABC):
    #: lowercase id, must match an entry in config.ALL_STORES
    name: str = ""
    #: human-friendly label for the UI
    label: str = ""

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[Product]:
        """Return the listings this adapter found. May be empty."""
        raise NotImplementedError

    async def check(self, client: httpx.AsyncClient) -> list[Product]:
        """Safe wrapper around :meth:`fetch` — never raises."""
        try:
            return await self.fetch(client)
        except Exception as err:  # noqa: BLE001
            log.warning("[source:%s] check failed: %s", self.name, err)
            return []
