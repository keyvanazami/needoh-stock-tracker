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
from .sources.facebook import fetch_page
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
        social_tasks = []
        for acct in settings.social_accounts:
            if acct.platform == "facebook":
                social_tasks.append(fetch_page(client, acct.account, acct.store))
            else:
                social_tasks.append(fetch_account(client, acct.account, acct.store))
        store_results = await asyncio.gather(*store_tasks) if store_tasks else []
        social_results = await asyncio.gather(*social_tasks) if social_tasks else []

    products = [p for batch in store_results for p in batch]
    sightings: list[RestockSighting] = [s for batch in social_results for s in batch]

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

    if fresh_sightings:
        await notifier.notify_sightings(fresh_sightings)

    # Call stores flagged for confirmation that just restocked or were named in a
    # fresh social restock hint. One call per store per cycle.
    called_stores: set[str] = set()
    triggers = [p.store for p in restocked] + [s.store for s in fresh_sightings if s.store]
    for store_id in triggers:
        if store_id in settings.call_stores and store_id not in called_stores:
            called_stores.add(store_id)
            await asyncio.to_thread(caller.call_store, store_id, source_label(store_id))

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
