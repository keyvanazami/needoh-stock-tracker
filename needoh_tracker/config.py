"""Runtime configuration, parsed from environment variables.

Every integration (SMTP, web push, Twilio, per-store phone numbers) is
optional. Missing config never crashes the app — the relevant feature just
logs that it is disabled and degrades to a no-op or "simulated" record.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import SocialAccount

SOCIAL_PLATFORMS: tuple[str, ...] = ("instagram", "facebook")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "needoh_frontend"

# Every store the app knows how to check, in display order. The Instagram
# watcher is handled separately (it produces sightings, not products).
ALL_STORES: tuple[str, ...] = ("schylling", "target", "walmart", "amazon")

# Restock keywords scanned in Instagram captions (lowercased substring match).
RESTOCK_KEYWORDS: tuple[str, ...] = (
    "restock",
    "re-stock",
    "back in stock",
    "back in-stock",
    "in stock",
    "in-stock",
    "available now",
    "now available",
    "shop now",
    "just dropped",
)

# Search terms the retailer adapters use.
SEARCH_TERMS: tuple[str, ...] = ("needoh", "nee doh", "nee-doh")


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_store_phones(value: str | None) -> dict[str, str]:
    """``"target=+15551234567,walmart=+15557654321"`` -> dict."""
    out: dict[str, str] = {}
    for pair in _split_csv(value):
        if "=" in pair:
            store, number = pair.split("=", 1)
            store = store.strip().lower()
            number = number.strip()
            if store and number:
                out[store] = number
    return out


@dataclass
class Settings:
    port: int = 3100
    poll_interval_s: int = 600
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "needoh-data")

    enabled_stores: list[str] = field(default_factory=lambda: list(ALL_STORES))
    # Social pages (Instagram/Facebook) watched for restock hints.
    social_accounts: list[SocialAccount] = field(default_factory=list)
    # Stores we should phone to ask about restocks (subset of enabled_stores).
    call_stores: list[str] = field(default_factory=list)

    # Email (SMTP)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_pass: str | None = None
    smtp_from: str | None = None
    smtp_to: list[str] = field(default_factory=list)

    # Web push (VAPID)
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:admin@example.com"

    # Twilio (real phone calls)
    twilio_sid: str | None = None
    twilio_token: str | None = None
    twilio_from: str | None = None
    store_phone_numbers: dict[str, str] = field(default_factory=dict)
    public_base_url: str | None = None

    # ---- derived helpers ----

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.smtp_to)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def twilio_enabled(self) -> bool:
        return bool(
            self.twilio_sid
            and self.twilio_token
            and self.twilio_from
            and self.public_base_url
        )

    def phone_for(self, store: str) -> str | None:
        return self.store_phone_numbers.get(store.lower())


def load_settings() -> Settings:
    """Build a Settings from os.environ. dotenv is loaded by the entrypoint."""
    enabled = _split_csv(os.environ.get("ENABLED_STORES")) or list(ALL_STORES)
    enabled = [s.lower() for s in enabled if s.lower() in ALL_STORES]
    if not enabled:
        enabled = list(ALL_STORES)

    call_stores = [s.lower() for s in _split_csv(os.environ.get("CALL_STORES"))]
    call_stores = [s for s in call_stores if s in ALL_STORES]

    social_accounts: list[SocialAccount] = []
    for handle in _split_csv(os.environ.get("INSTAGRAM_ACCOUNTS")):
        social_accounts.append(SocialAccount("instagram", handle.lstrip("@")))
    for handle in _split_csv(os.environ.get("FACEBOOK_ACCOUNTS")):
        social_accounts.append(SocialAccount("facebook", handle.strip("/")))

    return Settings(
        port=int(os.environ.get("PORT", "3100")),
        poll_interval_s=max(60, int(os.environ.get("POLL_INTERVAL_S", "600"))),
        enabled_stores=enabled,
        social_accounts=social_accounts,
        call_stores=call_stores,
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER") or None,
        smtp_pass=os.environ.get("SMTP_PASS") or None,
        smtp_from=os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or None,
        smtp_to=_split_csv(os.environ.get("SMTP_TO")),
        vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY") or None,
        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY") or None,
        vapid_subject=os.environ.get("VAPID_SUBJECT") or "mailto:admin@example.com",
        twilio_sid=os.environ.get("TWILIO_ACCOUNT_SID") or None,
        twilio_token=os.environ.get("TWILIO_AUTH_TOKEN") or None,
        twilio_from=os.environ.get("TWILIO_FROM_NUMBER") or None,
        store_phone_numbers=_parse_store_phones(os.environ.get("STORE_PHONE_NUMBERS")),
        public_base_url=(os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/") or None,
    )
