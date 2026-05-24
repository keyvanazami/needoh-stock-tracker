# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## What this is

A self-contained FastAPI app that tracks **NeeDoh** toy stock across retailers
(Schylling, Target, Walmart, Amazon) and Instagram, keeps a **deduped
watchlist**, notifies on restocks (live dashboard / web push / email), and can
place **automated Twilio phone calls** to stores about availability. It runs
standalone — no external services are required to boot.

## Run / test

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m needoh_tracker                 # serves http://localhost:3100
python -m unittest discover -s tests -p 'test_*.py'   # 12 tests, no network
```

Config is entirely env-driven (`.env`, all optional) — see `.env.example`.

## Layout

```
needoh_tracker/
  server.py      FastAPI app: REST + SSE + Twilio webhooks + static mount
  scheduler.py   background poll loop + single-cycle run_cycle()
  store.py       disk-backed JSON state (watchlist/history/sightings/calls/subs)
  notifier.py    SSE + Web Push (VAPID) + email (SMTP) fan-out
  phone.py       Twilio outbound calls + TwiML (real or "simulated")
  config.py      env-driven Settings; all integrations optional
  models.py      Product / RestockSighting / SocialAccount / CallRecord dataclasses
  sources/       one adapter per retailer + Instagram & Facebook social watchers
needoh_frontend/ static dashboard (watchlist, IG feed, call log, settings)
tests/           unit tests + fixtures (test_store.py, test_sources.py)
```

## Conventions & invariants (read before editing)

- **Source adapters must never raise.** `sources/base.py:RetailerSource.check`
  wraps `fetch` and turns any error into `[]`. New adapters subclass
  `RetailerSource`, set `name`/`label`, implement `async fetch(client)`, and get
  registered in `sources/__init__.py`. `name` must match an id in
  `config.ALL_STORES`.
- **Restock detection lives in `store.py:TrackerStore.apply_products`.** A
  product is a "restock" only on a genuine `False -> True` flip or first-seen
  while in stock — never on staying-in-stock. This is what prevents re-notifying
  every poll cycle. The store persists the last-known `in_stock` flag per product
  key (`store:sku`, or `store:hash(url)` when no sku). Keep this semantics intact.
- **Notifications fan out in `notifier.py`.** Three independent channels (SSE,
  web push, email); each no-ops + logs if unconfigured. `notify_restock` and
  `notify_sightings` are the entry points the scheduler calls.
- **Phone calls degrade to "simulated."** `phone.py:PhoneCaller.call_store`
  places a real Twilio call only when `settings.twilio_enabled` AND a per-store
  number exist; otherwise it records a `CallRecord(status="simulated")` carrying
  the script it would have spoken. TwiML is built in `phone.py` and served by
  `/twiml/voice` + `/twiml/gather` in `server.py`.
- **Single poll path.** `scheduler.run_cycle` is the one place that checks
  sources, merges into the store, and dispatches notifications + calls. Both the
  background loop and `POST /api/check` call it. Don't duplicate this logic.
- **Static mount is last** in `server.py` so explicit routes win (same pattern as
  the routes table in the module docstring).

## Gotchas

- **`pywebpush` is optional and has a fussy native dep** (`http-ece` →
  `cryptography`/`cffi`). It's guarded by a try/except import in `notifier.py`; if
  it isn't installed, background web push is disabled but everything else works.
  On a broken build, the in-app SSE + browser Notification path still delivers
  desktop notifications while the dashboard is open.
- **Live sources are frequently bot-blocked (HTTP 403).** Amazon/Walmart and
  Instagram block aggressively; results depend on network egress. Schylling's
  Shopify `products.json` and Target's RedSky JSON are the most reliable. Empty
  results are expected in locked-down environments, not a bug.
- **Parsers are tested against fixtures** in `tests/fixtures/`. When changing an
  adapter's parsing, update or add a fixture and a `test_sources.py` case rather
  than relying on live HTTP.
- **Scrape politely.** Default `POLL_INTERVAL_S=600` (10 min). High-frequency
  scraping risks site ToS.

## Adding things

- **New retailer:** add `sources/<name>.py` with a `RetailerSource` subclass + a
  pure parser function, register it in `sources/__init__.py`, add it to
  `config.ALL_STORES`, and add a fixture-backed parser test.
- **New social platform:** add `sources/<name>.py` with a pure
  `parse_*(account, body, store=None) -> list[RestockSighting]` + a
  `fetch_*(client, account, store=None)` that never raises (mirror
  `instagram.py`/`facebook.py`), add the id to `config.SOCIAL_PLATFORMS`, seed it
  from an env var in `load_settings`, and dispatch to it in `scheduler.run_cycle`.
  Social pages carry an optional `store` link (subset of `config.ALL_STORES`); a
  fresh hint for a `store` in `call_stores` triggers that store's auto-call.
- **New notification channel:** add a method in `notifier.py` and call it from
  `notify_restock`/`notify_sightings`; gate it behind a `config.Settings` flag.
