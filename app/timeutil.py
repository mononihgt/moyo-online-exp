from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return as_utc(parsed).replace(tzinfo=None)


def localize(value: datetime, timezone_name: str) -> datetime:
    return as_utc(value).astimezone(ZoneInfo(timezone_name))


def week_deadline_utc(value: datetime, timezone_name: str) -> datetime:
    local = localize(value, timezone_name)
    days_to_sunday = 6 - local.weekday()
    sunday = local.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta

    sunday = sunday + timedelta(days=days_to_sunday, hours=24)
    return sunday.astimezone(timezone.utc).replace(tzinfo=None)
