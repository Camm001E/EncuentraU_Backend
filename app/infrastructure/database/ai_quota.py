"""Atomic quota reservation. A failed reservation rolls back every counter."""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.domain.ai_quota import QuotaExceeded, QuotaUnavailable, quota_windows
from app.infrastructure.database.engine import DatabaseConfigurationError, get_engine


class PostgresAIQuota:
    def __init__(self, settings, engine=None):
        self.settings = settings
        self.engine = engine

    def reserve(self, user_id, units):
        if units not in (2, 3):
            raise ValueError("Unsupported AI operation")
        if not self.settings.ai_quota_enabled:
            return
        try:
            with (self.engine or get_engine()).begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '3s'"))
                now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                windows = quota_windows(user_id, now, self.settings)
                locked = []
                for window in windows:
                    params = dict(
                        scope=window.scope,
                        bucket=window.bucket,
                        expires=window.expires_at,
                    )
                    connection.execute(
                        text(
                            "INSERT INTO ai_quota_counters(scope,bucket,expires_at) "
                            "VALUES (:scope,:bucket,:expires) "
                            "ON CONFLICT(scope,bucket) DO NOTHING"
                        ),
                        params,
                    )
                    used = connection.execute(
                        text(
                            "SELECT used FROM ai_quota_counters "
                            "WHERE scope=:scope AND bucket=:bucket FOR UPDATE"
                        ),
                        params,
                    ).scalar_one()
                    locked.append((window, used))
                denied = [w for w, used in locked if used + units > w.limit]
                if denied:
                    raise QuotaExceeded(
                        max(int((w.expires_at - now).total_seconds()) for w in denied)
                        + 1
                    )
                for window, _ in locked:
                    connection.execute(
                        text(
                            "UPDATE ai_quota_counters SET used=used+:units "
                            "WHERE scope=:scope AND bucket=:bucket"
                        ),
                        dict(scope=window.scope, bucket=window.bucket, units=units),
                    )
        except (SQLAlchemyError, DatabaseConfigurationError):
            raise QuotaUnavailable from None
