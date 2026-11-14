from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.domain.ai_quota import quota_windows


@pytest.mark.parametrize(
    "instant,day,month",
    [
        ("2026-12-01T04:59:59+00:00", "2026-11-30", "2026-11-01"),
        ("2026-12-01T05:00:00+00:00", "2026-12-01", "2026-12-01"),
        ("2027-01-01T05:00:00+00:00", "2027-01-01", "2027-01-01"),
        ("2028-02-29T18:00:00+00:00", "2028-02-29", "2028-02-01"),
    ],
)
def test_colombia_day_and_month_boundaries(instant, day, month):
    now = datetime.fromisoformat(instant)
    windows = quota_windows("one", now, Settings(_env_file=None))
    assert windows[0].bucket.startswith(day)
    assert windows[1].bucket.startswith(month)
    assert all(w.expires_at > now for w in windows)
    assert all(w.expires_at.tzinfo == UTC for w in windows)


def test_global_windows_shared_user_windows_isolated():
    now = datetime(2026, 11, 14, tzinfo=UTC)
    settings = Settings(_env_file=None)
    a, b = [quota_windows(user, now, settings) for user in ("one", "two")]
    assert a[:2] == b[:2]
    assert {w.scope for w in a[2:]}.isdisjoint(w.scope for w in b[2:])
