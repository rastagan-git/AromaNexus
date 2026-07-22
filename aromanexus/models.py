"""Shared result and provenance models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now_iso() -> str:
    """Return a stable, timezone-aware retrieval timestamp."""

    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class LookupResult:
    """A provider response plus the minimum provenance needed for an export."""

    provider: str
    values: dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    retrieved_at: str = field(default_factory=utc_now_iso)
    status: str = "ok"
    message: str = ""
    cache_hit: bool = False
    version: str = ""
    license_url: str = ""

    @classmethod
    def failure(
        cls,
        provider: str,
        *,
        status: str,
        message: str,
        source_url: str = "",
        retrieved_at: str = "",
    ) -> LookupResult:
        return cls(
            provider=provider,
            status=status,
            message=message,
            source_url=source_url,
            retrieved_at=retrieved_at,
        )

    def provenance_columns(self, prefix: str | None = None) -> dict[str, Any]:
        """Flatten provenance for CSV or workbook output."""

        label = prefix or self.provider
        return {
            f"{label} Status": self.status,
            f"{label} Source URL": self.source_url,
            f"{label} Retrieved At": self.retrieved_at,
            f"{label} Cache Hit": self.cache_hit,
            f"{label} Version": self.version,
            f"{label} License URL": self.license_url,
            f"{label} Message": self.message,
        }
