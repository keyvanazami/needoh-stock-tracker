"""Plain data records shared across the app.

Kept as dataclasses (not Pydantic) since they're internal; JSON serialization
goes through ``to_dict`` for the API and the disk store.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Product:
    """A single retailer listing for a NeeDoh product."""

    name: str
    store: str
    url: str
    in_stock: bool
    price: float | None = None
    image: str | None = None
    sku: str | None = None
    last_checked: str = field(default_factory=_now_iso)

    @property
    def key(self) -> str:
        """Stable identity for dedupe/history. Prefer store+sku; fall back to
        a hash of store+url so listings without a SKU still dedupe cleanly."""
        if self.sku:
            return f"{self.store}:{self.sku}"
        digest = hashlib.sha1(f"{self.store}:{self.url}".encode()).hexdigest()[:12]
        return f"{self.store}:{digest}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        return data


@dataclass
class RestockSighting:
    """An Instagram post whose caption hints a restock."""

    account: str
    post_url: str
    caption: str
    matched_keyword: str
    seen_at: str = field(default_factory=_now_iso)

    @property
    def key(self) -> str:
        digest = hashlib.sha1(self.post_url.encode()).hexdigest()[:12]
        return f"ig:{self.account}:{digest}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        return data


@dataclass
class CallRecord:
    """A phone call placed (or simulated) to a store about NeeDoh stock."""

    store: str
    to_number: str | None
    status: str  # "queued" | "completed" | "failed" | "simulated"
    script: str
    sid: str | None = None
    result: str | None = None  # speech transcript / answer, if gathered
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)
