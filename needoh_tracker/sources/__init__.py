"""Retailer source registry."""
from __future__ import annotations

from .amazon import AmazonSource
from .base import RetailerSource
from .schylling import SchyllingSource
from .target import TargetSource
from .walmart import WalmartSource

# Keyed by RetailerSource.name (matches config.ALL_STORES).
_REGISTRY: dict[str, RetailerSource] = {
    src.name: src
    for src in (SchyllingSource(), TargetSource(), WalmartSource(), AmazonSource())
}


def get_sources(enabled: list[str]) -> list[RetailerSource]:
    """Return adapter instances for the enabled store ids, in config order."""
    return [_REGISTRY[name] for name in enabled if name in _REGISTRY]


def source_label(name: str) -> str:
    src = _REGISTRY.get(name)
    return src.label if src else name


__all__ = ["RetailerSource", "get_sources", "source_label"]
