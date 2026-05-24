"""Automated store phone calls via Twilio.

A real outbound call needs (a) Twilio credentials and (b) a publicly reachable
``PUBLIC_BASE_URL`` so Twilio can fetch the call's TwiML and post the gathered
speech back. When either is missing, :meth:`PhoneCaller.call_store` records a
``simulated`` CallRecord containing the exact script it would have spoken, so
the whole flow stays visible and testable without paid infrastructure.

The spoken script asks whether a store has NeeDoh toys in stock and, if not,
when they expect a restock; ``<Gather input="speech">`` captures the reply.
"""
from __future__ import annotations

import logging
from xml.sax.saxutils import escape

from .config import Settings
from .models import CallRecord
from .store import TrackerStore

log = logging.getLogger(__name__)

try:  # optional dep; only needed for real calls
    from twilio.rest import Client as TwilioClient
except Exception:  # noqa: BLE001
    TwilioClient = None  # type: ignore[assignment,misc]


def build_script(store_label: str) -> str:
    return (
        f"Hello! I'm calling on behalf of a customer to ask about your toy "
        f"inventory at {store_label}. Do you currently have any Nee Doh squishy "
        f"stress toys in stock? If they are out of stock, please say when you "
        f"expect them to be available again. Please answer after the beep."
    )


def build_voice_twiml(store_label: str, gather_action: str) -> str:
    """TwiML served to Twilio when the call connects."""
    script = escape(build_script(store_label))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather input="speech" speechTimeout="auto" method="POST" action="{escape(gather_action)}">'
        f'<Say voice="Polly.Joanna">{script}</Say>'
        "</Gather>"
        '<Say voice="Polly.Joanna">Sorry, I did not catch that. Goodbye.</Say>'
        "</Response>"
    )


def build_gather_response_twiml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Say voice="Polly.Joanna">Thank you very much. Goodbye.</Say>'
        "<Hangup/>"
        "</Response>"
    )


class PhoneCaller:
    def __init__(self, settings: Settings, store: TrackerStore) -> None:
        self._settings = settings
        self._store = store

    def call_store(self, store: str, store_label: str) -> CallRecord:
        """Place (or simulate) a call to ``store``. Returns the logged record."""
        s = self._settings
        to_number = s.phone_for(store)
        script = build_script(store_label)

        if not s.twilio_enabled or not to_number or TwilioClient is None:
            reason = []
            if not s.twilio_enabled:
                reason.append("twilio/public-url not configured")
            if not to_number:
                reason.append(f"no phone number for '{store}'")
            if TwilioClient is None:
                reason.append("twilio package missing")
            log.info("[phone] simulating call to %s (%s)", store, "; ".join(reason))
            record = CallRecord(
                store=store,
                to_number=to_number,
                status="simulated",
                script=script,
                result="; ".join(reason),
            )
            self._store.add_call(record)
            return record

        voice_url = f"{s.public_base_url}/twiml/voice?store={store}"
        try:
            client = TwilioClient(s.twilio_sid, s.twilio_token)
            call = client.calls.create(to=to_number, from_=s.twilio_from, url=voice_url)
            record = CallRecord(
                store=store, to_number=to_number, status="queued", script=script, sid=call.sid
            )
            log.info("[phone] placed call to %s (sid=%s)", store, call.sid)
        except Exception as err:  # noqa: BLE001
            log.warning("[phone] call to %s failed: %s", store, err)
            record = CallRecord(
                store=store, to_number=to_number, status="failed", script=script, result=str(err)
            )
        self._store.add_call(record)
        return record
