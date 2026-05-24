"""Background polling loop and the single-cycle ``run_cycle`` it drives.

``run_cycle`` runs every enabled retailer adapter (plus the Instagram watcher)
in parallel over a shared httpx client — mirroring ``research.gather_sources``
in the existing backend — merges results into the store, and fires
notifications + store calls for anything that just restocked.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from .config import Settings
from .models import RestockSighting
from .notifier import Notifier
from .phone import PhoneCaller
from .sources import get_sources, source_label
from .sources.instagram import fetch_account
from .store import TrackerStore

log = logging.getLogger(__name__)


async def run_cycle(
    settings: Settings,
    store: TrackerStore,
    notifier: Notifier,
    caller: PhoneCaller,
) -> dict:
    """One poll: check stores + Instagram, persist, notify, maybe call.

    Returns a small summary dict (used by the manual ``POST /api/check``).
    """
    sources = get_sources(settings.enabled_stores)
    async with httpx.AsyncClient() as client:
        store_tasks = [src.check(client) for src in sources]
        ig_tasks = [fetch_account(client, acct) for acct in settings.instagram_accounts]
        store_results = await asyncio.gather(*store_tasks) if store_tasks else []
        ig_results = await asyncio.gather(*ig_tasks) if ig_tasks else []

    products = [p for batch in store_results for p in batch]
    sightings: list[RestockSighting] = [s for batch in ig_results for s in batch]

    restocked = store.apply_products(products)
    fresh_sightings = store.add_sightings(sightings)

    await notifier.broadcast(
        {
            "type": "cycle",
            "checked": len(products),
            "restocked": len(restocked),
            "sightings": len(fresh_sightings),
        }
    )

    if restocked:
        await notifier.notify_restock(restocked)
        # Call stores flagged for confirmation that just restocked.
        called_stores: set[str] = set()
        for product in restocked:
            if product.store in settings.call_stores and product.store not in called_stores:
                called_stores.add(product.store)
                await asyncio.to_thread(
                    caller.call_store, product.store, source_label(product.store)
                )

    if fresh_sightings:
        await notifier.notify_sightings(fresh_sightings)

    summary = {
        "checked": len(products),
        "restocked": len(restocked),
        "new_sightings": len(fresh_sightings),
        "stores": settings.enabled_stores,
    }
    log.info("[cycle] %s", summary)
    return summary


async def poll_loop(
    settings: Settings,
    store: TrackerStore,
    notifier: Notifier,
    caller: PhoneCaller,
) -> None:
    """Run forever, one cycle per ``poll_interval_s``. Cancelled on shutdown."""
    log.info("[scheduler] polling every %ss; stores=%s", settings.poll_interval_s, settings.enabled_stores)
    while True:
        try:
            await run_cycle(settings, store, notifier, caller)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            log.warning("[scheduler] cycle error: %s", err)
        await asyncio.sleep(settings.poll_interval_s)
