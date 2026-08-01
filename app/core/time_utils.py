"""UTC-safe helpers for persisted timestamps and runtime comparisons."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # Historical timestamp columns stored values as UTC without tzinfo.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
