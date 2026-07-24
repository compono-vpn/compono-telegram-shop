import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.constants import TIMEZONE

START_TIME: int = int(time.time())

MSK: ZoneInfo = ZoneInfo("Europe/Moscow")


def datetime_now() -> datetime:
    return datetime.now(tz=TIMEZONE)


def get_uptime() -> int:  # TODO: Think about where to put this
    return int(time.time() - START_TIME)


def to_rfc3339_utc(dt: datetime) -> str:
    """Format a datetime as an RFC3339 UTC timestamp (e.g. 2026-07-23T00:00:00+00:00)."""
    aware_dt = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return aware_dt.astimezone(timezone.utc).isoformat()


def compute_msk_previous_day_window(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC bounds of the previous full MSK calendar day.

    E.g. if `now` falls on the morning of July 24 MSK, returns the UTC bounds
    covering all of July 23, 00:00:00 MSK (inclusive) through July 24, 00:00:00
    MSK (exclusive).

    `now` may be naive (assumed to already be MSK local time) or timezone-aware
    (converted to MSK). Defaults to the current time in MSK when omitted.
    """
    if now is None:
        now_msk = datetime.now(tz=MSK)
    elif now.tzinfo is None:
        now_msk = now.replace(tzinfo=MSK)
    else:
        now_msk = now.astimezone(MSK)

    today_msk = now_msk.date()
    yesterday_msk = today_msk - timedelta(days=1)

    start_msk = datetime(yesterday_msk.year, yesterday_msk.month, yesterday_msk.day, tzinfo=MSK)
    end_msk = datetime(today_msk.year, today_msk.month, today_msk.day, tzinfo=MSK)

    return start_msk.astimezone(timezone.utc), end_msk.astimezone(timezone.utc)
