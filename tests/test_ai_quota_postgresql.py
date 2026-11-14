import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.domain.ai_quota import QuotaExceeded
from app.infrastructure.database.ai_quota import PostgresAIQuota


@pytest.fixture
def ledger():
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Isolated PostgreSQL required")
    assert "_test" in make_url(raw).database
    schema = "quota_test_" + uuid4().hex
    control = create_engine(raw)
    with control.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    engine = create_engine(raw, connect_args={"options": "-csearch_path=" + schema})
    with engine.begin() as c:
        c.execute(
            text(
                "CREATE TABLE ai_quota_counters (scope varchar(80), "
                "bucket varchar(40), "
                "used integer NOT NULL DEFAULT 0 CHECK(used>=0), "
                "expires_at timestamptz NOT NULL, PRIMARY KEY(scope,bucket))"
            )
        )
    settings = Settings(
        _env_file=None,
        ai_quota_enabled=True,
        ai_quota_user_hour=6,
        ai_quota_user_day=20,
        ai_quota_global_day=120,
        ai_quota_global_month=1200,
    )
    try:
        yield PostgresAIQuota(settings, engine)
    finally:
        engine.dispose()
        with control.begin() as c:
            c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        control.dispose()


def test_parallel_requests_cannot_overspend(ledger):
    def reserve(_):
        try:
            ledger.reserve("one", 2)
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(reserve, range(12)))
    assert sum(results) == 3
    with ledger.engine.connect() as c:
        assert c.execute(
            text("SELECT min(used),max(used) FROM ai_quota_counters")
        ).one() == (6, 6)


def test_denied_reservation_changes_no_counter(ledger):
    ledger.reserve("one", 3)
    ledger.reserve("one", 3)
    with ledger.engine.connect() as c:
        before = c.execute(
            text("SELECT scope,bucket,used FROM ai_quota_counters ORDER BY scope")
        ).all()
    with pytest.raises(QuotaExceeded):
        ledger.reserve("one", 2)
    with ledger.engine.connect() as c:
        after = c.execute(
            text("SELECT scope,bucket,used FROM ai_quota_counters ORDER BY scope")
        ).all()
    assert after == before


def test_new_ledger_and_connections_do_not_reset_allowance(ledger):
    ledger.reserve("one", 3)
    ledger.reserve("one", 3)
    ledger.engine.dispose()
    fresh = PostgresAIQuota(ledger.settings, ledger.engine)
    with pytest.raises(QuotaExceeded):
        fresh.reserve("one", 2)
    fresh.reserve("two", 2)


def test_global_allowance_is_shared_between_accounts(ledger):
    ledger.settings.ai_quota_global_day = 6
    for user in ("one", "two", "three"):
        ledger.reserve(user, 2)
    with pytest.raises(QuotaExceeded):
        ledger.reserve("four", 2)
    with ledger.engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM ai_quota_counters "
                    "WHERE scope LIKE 'user:four:%'"
                )
            ).scalar_one()
            == 0
        )


def test_monthly_allowance_independently_stops_spending(ledger):
    ledger.settings.ai_quota_global_month = 3
    ledger.reserve("one", 3)
    with pytest.raises(QuotaExceeded) as exc:
        ledger.reserve("two", 2)
    assert exc.value.retry_after > 0


def test_obsolete_counter_cleanup_preserves_recent_history(ledger):
    with ledger.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO ai_quota_counters VALUES "
                "('old','old',2,now()-interval '45 days'),"
                "('recent','recent',2,now()-interval '1 day')"
            )
        )
    ledger.reserve("one", 2)
    with ledger.engine.connect() as c:
        scopes = set(c.execute(text("SELECT scope FROM ai_quota_counters")).scalars())
    assert "old" not in scopes and "recent" in scopes
