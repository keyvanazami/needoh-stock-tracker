# Handoff — NeeDoh Stock Tracker

Context for picking this project up in a fresh Claude Code session.

## How to continue

This repo was built in a session scoped to a *different* repo (`live-test`), so
that session can't push here. To work on this project, start a **new Claude Code
on the web session whose source repo is `keyvanazami/needoh-stock-tracker`** —
that session's tools will be scoped to this repo and can branch/commit/push.
Then paste the "Paste-ready brief" below as your first message.

## What was built & why

The ask: an app that finds NeeDoh toys, lists them, notifies you when they're in
stock, "calls stores" to ask about restocks, gives product info, and watches
Instagram for restock announcements.

Decisions made (user chose the ambitious options):
- **Real sources where possible**, with graceful degradation — adapters hit real
  endpoints (Schylling Shopify JSON, Target RedSky JSON, Walmart/Amazon HTML) and
  return `[]` on any failure rather than crashing. Many sites bot-block (HTTP
  403), so live results depend on network egress; Schylling/Target are most
  reliable.
- **Real phone calls** via Twilio — but gated on Twilio creds + a public webhook
  URL. Without them, calls are recorded as `simulated` with the exact spoken
  script, so the flow is fully testable offline.
- **Notifications**: live dashboard (SSE) + browser/desktop **web push** (VAPID)
  + **email** (SMTP). All optional; each no-ops if unconfigured.
- **Stack**: FastAPI + uvicorn + httpx + BeautifulSoup, static vanilla-JS
  dashboard. Disk-backed JSON store. Background poll loop every 10 min.

## Current state

- Feature-complete and committed; the standalone repo at this root has been
  pushed to `main` on GitHub.
- 12 unit tests pass (restock dedupe + all source parsers, fixture-backed).
- Verified end-to-end: server boots, dashboard serves, `/api/check` runs a poll,
  a forced `out -> in` flip fires a `restock` SSE event + an auto-call (simulated
  in test), and the simulated-call endpoint returns the script.
- Known-empty in sandboxes: live retailer/Instagram calls returned 403 in the
  build environment (expected; adapters fail soft).

## Not done yet / candidate next steps

- GitHub Actions CI to run the tests on push (offered, not added).
- `pyproject.toml` for `pip install`-able packaging (offered, not added).
- Generating a real VAPID keypair / wiring Gmail SMTP / Twilio for live use.
- More retailers (e.g. Kohl's, Five Below, Barnes & Noble) — add a
  `RetailerSource` subclass + fixture test (see CLAUDE.md "Adding things").

## Read these first

`CLAUDE.md` (conventions & invariants), then `README.md` (setup/API), then
`needoh_tracker/scheduler.py` → `store.py` → `notifier.py` to trace the poll path.

---

## Paste-ready brief (drop into the new session's first message)

> I'm continuing work on the NeeDoh Stock Tracker (this repo). It's a FastAPI app
> that tracks NeeDoh toy stock across Schylling/Target/Walmart/Amazon + Instagram,
> keeps a deduped watchlist, notifies on restocks via SSE/web-push/email, and
> places automated Twilio calls to stores (simulated when Twilio isn't
> configured). Read CLAUDE.md for conventions and HANDOFF.md for background. Key
> invariants: source adapters must never raise (sources/base.py), and restock
> detection only fires on a False→True flip or first-seen-in-stock
> (store.py:apply_products). Run with `python -m needoh_tracker` (port 3100);
> tests via `python -m unittest discover -s tests -p 'test_*.py'`. Next up I'd
> like to: <YOUR TASK HERE>.
