"""FastAPI app for the NeeDoh Stock Tracker.

Routes
  GET  /healthz                 — health probe
  GET  /api/products            — current watchlist + stock
  POST /api/check               — run one poll cycle now
  GET  /api/sightings           — Instagram restock feed
  GET  /api/calls               — call log
  POST /api/calls/{store}       — place/simulate a call to a store
  POST /twiml/voice             — Twilio webhook: spoken script + speech gather
  POST /twiml/gather            — Twilio webhook: store gathered speech
  GET  /api/settings            — current (non-secret) config
  POST /api/settings            — update poll interval / store toggles at runtime
  GET  /api/config              — public bits the frontend needs (VAPID key)
  GET  /events                  — SSE stream of live updates
  POST /api/push/subscribe      — register a web-push subscription
  POST /api/push/unsubscribe    — drop a web-push subscription
  GET  /                        — static dashboard (mounted last)
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import ALL_STORES, FRONTEND_DIR, SOCIAL_PLATFORMS, load_settings
from .models import SocialAccount
from .notifier import Notifier
from .phone import PhoneCaller, build_gather_response_twiml, build_voice_twiml
from .scheduler import poll_loop, run_cycle
from .sources import source_label
from .store import TrackerStore

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("needoh_tracker.server")

load_dotenv()

settings = load_settings()
store = TrackerStore(settings.data_dir)
notifier = Notifier(settings, store)
caller = PhoneCaller(settings, store)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    task = asyncio.create_task(poll_loop(settings, store, notifier, caller))
    log.info("[server] http://localhost:%s", settings.port)
    log.info(
        "[server] email=%s push=%s twilio=%s",
        settings.email_enabled,
        settings.push_enabled,
        settings.twilio_enabled,
    )
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


app = FastAPI(lifespan=_lifespan, title="NeeDoh Stock Tracker")


# ---------- health + config ----------

@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "app": "needoh-tracker",
        "stores": settings.enabled_stores,
        "email": settings.email_enabled,
        "push": settings.push_enabled,
        "twilio": settings.twilio_enabled,
    }


@app.get("/api/config")
async def api_config() -> dict:
    """Non-secret bits the frontend needs."""
    return {
        "vapidPublicKey": settings.vapid_public_key,
        "pushEnabled": settings.push_enabled,
        "pollIntervalS": settings.poll_interval_s,
    }


# ---------- products + cycle ----------

@app.get("/api/products")
async def api_products() -> dict:
    return {"products": store.list_products()}


@app.post("/api/check")
async def api_check() -> dict:
    summary = await run_cycle(settings, store, notifier, caller)
    return {"ok": True, "summary": summary, "products": store.list_products()}


# ---------- instagram sightings ----------

@app.get("/api/sightings")
async def api_sightings() -> dict:
    return {"sightings": store.list_sightings()}


# ---------- calls ----------

@app.get("/api/calls")
async def api_calls() -> dict:
    return {"calls": store.list_calls()}


@app.post("/api/calls/{store_id}")
async def api_call_store(store_id: str) -> dict:
    store_id = store_id.lower()
    if store_id not in ALL_STORES:
        raise HTTPException(status_code=404, detail=f"unknown store '{store_id}'")
    record = await asyncio.to_thread(caller.call_store, store_id, source_label(store_id))
    await notifier.broadcast({"type": "call", "call": record.to_dict()})
    return {"ok": True, "call": record.to_dict()}


# ---------- Twilio webhooks ----------

@app.post("/twiml/voice")
async def twiml_voice(request: Request) -> Response:
    store_id = request.query_params.get("store", "the store")
    label = source_label(store_id)
    gather_action = f"{settings.public_base_url or ''}/twiml/gather?store={store_id}"
    xml = build_voice_twiml(label, gather_action)
    return Response(content=xml, media_type="application/xml")


@app.post("/twiml/gather")
async def twiml_gather(request: Request) -> Response:
    form = await request.form()
    speech = str(form.get("SpeechResult") or "")
    sid = str(form.get("CallSid") or "")
    if sid:
        store.update_call_result(sid, speech or "(no speech captured)", status="completed")
        await notifier.broadcast({"type": "call_result", "sid": sid, "result": speech})
    return Response(content=build_gather_response_twiml(), media_type="application/xml")


# ---------- settings ----------

@app.get("/api/settings")
async def api_get_settings() -> dict:
    return {
        "pollIntervalS": settings.poll_interval_s,
        "enabledStores": settings.enabled_stores,
        "allStores": list(ALL_STORES),
        "callStores": settings.call_stores,
        "socialAccounts": [a.to_dict() for a in settings.social_accounts],
        "socialPlatforms": list(SOCIAL_PLATFORMS),
        "storeLabels": {s: source_label(s) for s in ALL_STORES},
    }


@app.post("/api/settings")
async def api_set_settings(request: Request) -> dict:
    body = await request.json()
    if isinstance(body, dict):
        if "pollIntervalS" in body:
            try:
                settings.poll_interval_s = max(60, int(body["pollIntervalS"]))
            except (TypeError, ValueError):
                pass
        if isinstance(body.get("enabledStores"), list):
            settings.enabled_stores = [s for s in body["enabledStores"] if s in ALL_STORES] or list(ALL_STORES)
        if isinstance(body.get("callStores"), list):
            settings.call_stores = [s for s in body["callStores"] if s in ALL_STORES]
        if isinstance(body.get("socialAccounts"), list):
            settings.social_accounts = _parse_social_accounts(body["socialAccounts"])
    return await api_get_settings()


def _parse_social_accounts(raw: list) -> list[SocialAccount]:
    accounts: list[SocialAccount] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or "").strip().lower()
        if platform not in SOCIAL_PLATFORMS:
            continue
        handle = str(item.get("account") or "").strip().lstrip("@").strip("/")
        if not handle:
            continue
        store = item.get("store")
        store = store if store in ALL_STORES else None
        dedupe = (platform, handle.lower())
        if dedupe in seen:
            continue
        seen.add(dedupe)
        accounts.append(SocialAccount(platform=platform, account=handle, store=store))
    return accounts


# ---------- web push subscriptions ----------

@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request) -> dict:
    sub = await request.json()
    if not isinstance(sub, dict) or not sub.get("endpoint"):
        raise HTTPException(status_code=400, detail="invalid subscription")
    store.add_subscription(sub)
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def api_push_unsubscribe(request: Request) -> dict:
    body = await request.json()
    endpoint = (body or {}).get("endpoint") if isinstance(body, dict) else None
    if endpoint:
        store.remove_subscription(endpoint)
    return {"ok": True}


# ---------- SSE ----------

@app.get("/events")
async def events() -> StreamingResponse:
    queue = notifier.register_sse()

    async def stream():
        try:
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # comment frame keeps the connection warm
        finally:
            notifier.unregister_sse(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- static frontend (LAST so explicit routes win) ----------

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
