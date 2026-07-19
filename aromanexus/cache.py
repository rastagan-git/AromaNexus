"""Cache-location migration helpers for the AromaNexus rename."""

from __future__ import annotations

import os
from pathlib import Path


def default_cache_root() -> Path:
    """Return the configured cache root, reusing a legacy cache when present."""

    configured = os.environ.get("AROMANEXUS_CACHE_DIR") or os.environ.get(
        "FLAVOR_DATA_CRAWLER_CACHE"
    )
    if configured:
        return Path(configured).expanduser()

    primary = Path.home() / ".cache" / "aromanexus"
    legacy = Path.home() / ".cache" / "flavor-data-crawler"
    if not primary.exists() and legacy.exists():
        return legacy
    return primary


def default_http_cache_dir() -> Path:
    """Return the HTTP cache directory with legacy environment compatibility."""

    legacy_http = os.environ.get("FLAVOR_DATA_CACHE_DIR")
    if legacy_http and not os.environ.get("AROMANEXUS_CACHE_DIR"):
        return Path(legacy_http).expanduser()
    return default_cache_root() / "http"


__all__ = ["default_cache_root", "default_http_cache_dir"]
