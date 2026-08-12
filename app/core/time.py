"""Timezone-aware UTC helpers — replace datetime.utcnow everywhere."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC time as an aware datetime."""
    return datetime.now(timezone.utc)
