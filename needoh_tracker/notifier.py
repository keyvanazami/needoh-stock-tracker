"""Notification fan-out: in-app SSE, browser web push (VAPID), and email (SMTP).

Each channel is independent and degrades to a logged no-op when unconfigured,
so the app is fully usable with zero notification setup (you still get the live
dashboard). ``notify_restock`` and ``notify_sightings`` are the two entry points
the scheduler calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from email.message import EmailMessage

from .config import Settings
from .models import Product, RestockSighting
from .store import TrackerStore

log = logging.getLogger(__name__)

try:  # optional dep; only needed when push is configured
    from pywebpush import WebPushException, webpush
except Exception:  # noqa: BLE001
    webpush = None
    WebPushException = Exception  # type: ignore[assignment,misc]


class Notifier:
    def __init__(self, settings: Settings, store: TrackerStore) -> None:
        self._settings = settings
        self._store = store
        # Connected SSE clients. Each is an asyncio.Queue of JSON-serializable
        # event dicts.
        self._sse_clients: set[asyncio.Queue] = set()

    # ---- SSE plumbing ----

    def register_sse(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._sse_clients.add(queue)
        return queue

    def unregister_sse(self, queue: asyncio.Queue) -> None:
        self._sse_clients.discard(queue)

    async def broadcast(self, event: dict) -> None:
        for queue in list(self._sse_clients):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow client; drop this event for them

    # ---- public entry points ----

    async def notify_restock(self, products: list[Product]) -> None:
        if not products:
            return
        await self.broadcast({"type": "restock", "products": [p.to_dict() for p in products]})
        title = "NeeDoh restock!" if len(products) == 1 else f"{len(products)} NeeDoh restocks!"
        lines = [f"- {p.name} @ {p.store}" + (f" (${p.price:.2f})" if p.price else "") + f"\n  {p.url}" for p in products]
        body = "These NeeDoh products just came back in stock:\n\n" + "\n".join(lines)
        await self._push(title, body, url=products[0].url)
        await self._email(title, body)

    async def notify_sightings(self, sightings: list[RestockSighting]) -> None:
        if not sightings:
            return
        await self.broadcast({"type": "sighting", "sightings": [s.to_dict() for s in sightings]})
        title = "NeeDoh Instagram restock hint"
        body = "\n\n".join(f"@{s.account}: {s.caption}\n{s.post_url}" for s in sightings)
        await self._push(title, body, url=sightings[0].post_url)
        await self._email(title, body)

    # ---- channels ----

    async def _push(self, title: str, body: str, url: str | None = None) -> None:
        if not self._settings.push_enabled:
            return
        if webpush is None:
            log.warning("[notify] push configured but pywebpush is not installed")
            return
        payload = json.dumps({"title": title, "body": body, "url": url})
        subs = self._store.list_subscriptions()
        for sub in subs:
            try:
                await asyncio.to_thread(
                    webpush,
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self._settings.vapid_private_key,
                    vapid_claims={"sub": self._settings.vapid_subject},
                )
            except WebPushException as err:  # noqa: BLE001
                # 404/410 => subscription dead; prune it.
                status = getattr(getattr(err, "response", None), "status_code", None)
                if status in (404, 410):
                    self._store.remove_subscription(sub.get("endpoint", ""))
                log.warning("[notify] push failed (%s): %s", status, err)
            except Exception as err:  # noqa: BLE001
                log.warning("[notify] push error: %s", err)

    async def _email(self, subject: str, body: str) -> None:
        if not self._settings.email_enabled:
            return
        try:
            await asyncio.to_thread(self._send_email_sync, subject, body)
        except Exception as err:  # noqa: BLE001
            log.warning("[notify] email failed: %s", err)

    def _send_email_sync(self, subject: str, body: str) -> None:
        s = self._settings
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = s.smtp_from
        msg["To"] = ", ".join(s.smtp_to)
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except smtplib.SMTPException:
                pass  # server may not support STARTTLS (e.g. local relay)
            if s.smtp_user and s.smtp_pass:
                server.login(s.smtp_user, s.smtp_pass)
            server.send_message(msg)
        log.info("[notify] email sent to %s", ", ".join(s.smtp_to))
