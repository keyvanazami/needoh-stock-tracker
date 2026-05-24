# NeeDoh Stock Tracker

Hunts for [NeeDoh](https://schylling.com) squishy toys across retailers and
Instagram, keeps a deduped watchlist, and notifies you the moment something
comes back in stock. It can even place automated phone calls to stores to ask
about availability.

- **Sources**: Schylling (official), Target, Walmart, Amazon, plus an Instagram
  restock-keyword watcher. Each adapter degrades gracefully — a blocked or
  changed source returns nothing instead of crashing the poll.
- **Smart restock detection**: only alerts on a genuine `out → in` flip (or a
  product first seen in stock), so a long-in-stock item doesn't re-notify every
  cycle.
- **Notifications**: live web dashboard (SSE), browser/desktop push (Web Push /
  VAPID), and email (SMTP). Each channel is optional and no-ops if unconfigured.
- **Automated store calls**: on a restock (or on demand) it can call a store via
  Twilio, speak a script asking about NeeDoh stock, and capture the reply. With
  no Twilio config it records a *simulated* call showing the exact script.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # optional — tweak as you like
python -m needoh_tracker                             # http://localhost:3100
```

Open <http://localhost:3100>, click **Check now**, and **Enable notifications**.
The tracker also polls automatically every `POLL_INTERVAL_S` seconds.

## How it works

```
needoh_tracker/
  server.py        FastAPI app: REST + SSE + Twilio webhooks + static dashboard
  scheduler.py     background poll loop + single-cycle run_cycle()
  store.py         disk-backed state (watchlist/history/sightings/calls/subs)
  notifier.py      SSE + Web Push + email fan-out
  phone.py         Twilio outbound calls + TwiML (real or simulated)
  config.py        env-driven Settings (all integrations optional)
  models.py        Product / RestockSighting / CallRecord
  sources/         one adapter per retailer + the Instagram watcher
needoh_frontend/   dashboard (watchlist, IG feed, call log, settings)
```

A poll runs every enabled adapter in parallel, merges results into the store,
diffs each product's last-known stock flag to find real restocks, then fans out
notifications and (for stores you've flagged) places calls.

## Configuration

All via environment variables / `.env` — see [`.env.example`](.env.example).
Highlights:

| Var | Purpose |
| --- | --- |
| `POLL_INTERVAL_S` | Seconds between polls (default 600). |
| `ENABLED_STORES` | Which retailers to check. |
| `INSTAGRAM_ACCOUNTS` | Accounts whose captions are scanned for restock keywords. |
| `CALL_STORES` | Stores to auto-call on a restock. |
| `SMTP_*` | Email alerts (Gmail: use an App Password). |
| `VAPID_*` | Web Push keypair for desktop/background notifications. |
| `TWILIO_*`, `PUBLIC_BASE_URL`, `STORE_PHONE_NUMBERS` | Real phone calls. |

### Notifications
- **In-app/desktop (no setup):** keep the dashboard open and grant notification
  permission — restocks pop a desktop notification via SSE.
- **Background push:** set `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` (generate with
  `vapid --gen` from `py-vapid`, or any VAPID tool) to get push even when the tab
  is closed (via the service worker).
- **Email:** set the `SMTP_*` vars.

### Phone calls
Real calls need a Twilio account **and** a public URL Twilio can reach for the
TwiML webhooks (e.g. an [ngrok](https://ngrok.com) tunnel to your local port),
plus per-store numbers in `STORE_PHONE_NUMBERS`. Without them, calls are logged
as `simulated` with the script they would have spoken — so the flow is fully
testable offline.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/healthz` | Health + which integrations are configured. |
| GET | `/api/products` | Current watchlist with stock. |
| POST | `/api/check` | Run one poll cycle now. |
| GET | `/api/sightings` | Instagram restock feed. |
| GET/POST | `/api/calls`, `/api/calls/{store}` | Call log / place a call. |
| GET/POST | `/api/settings` | Read / update poll interval & toggles at runtime. |
| GET | `/events` | SSE stream of live updates. |
| POST | `/api/push/subscribe` | Register a Web Push subscription. |
| POST | `/twiml/voice`, `/twiml/gather` | Twilio call webhooks. |

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py'   # or: pytest tests
```

Covers restock dedupe logic and every source parser against saved fixtures
(no network required).

## Caveats
- Retailers (especially Amazon/Walmart) and Instagram aggressively block bots, so
  live results depend on your network egress; adapters fail soft to `[]`.
  Schylling's Shopify feed and Target's RedSky JSON are the most reliable.
- Scrape responsibly: the default 10-minute interval keeps this to polite,
  personal use. High-frequency scraping may violate site terms.

## License

MIT — see [LICENSE](LICENSE).
