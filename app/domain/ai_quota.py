"""Conservative provider-call allowances, using Colombia calendar boundaries."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

ANALYSIS_UNITS = 2  # Primary and possible fallback.
COMPARISON_UNITS = 3  # Primary, possible fallback and difference audit.


class QuotaExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)


class QuotaUnavailable(Exception):
    pass


@dataclass(frozen=True)
class QuotaWindow:
    scope: str
    bucket: str
    expires_at: datetime
    limit: int


def quota_windows(user_id, now, settings):
    local = now.astimezone(ZoneInfo("America/Bogota"))
    hour = local.replace(minute=0, second=0, microsecond=0)
    day = hour.replace(hour=0)
    month = day.replace(day=1)
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    specs = [
        ("global:day", day, day + timedelta(days=1), settings.ai_quota_global_day),
        ("global:month", month, next_month, settings.ai_quota_global_month),
        (
            f"user:{user_id}:day",
            day,
            day + timedelta(days=1),
            settings.ai_quota_user_day,
        ),
        (
            f"user:{user_id}:hour",
            hour,
            hour + timedelta(hours=1),
            settings.ai_quota_user_hour,
        ),
    ]
    return [
        QuotaWindow(scope, start.isoformat(), end.astimezone(UTC), limit)
        for scope, start, end, limit in specs
    ]
