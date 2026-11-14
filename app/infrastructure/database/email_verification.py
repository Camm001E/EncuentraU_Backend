import hashlib
import hmac
import math
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.domain.authentication import (
    AuthenticationUnavailableError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidVerificationCodeError,
    VerificationRateLimitError,
)
from app.domain.users import normalize_email
from app.infrastructure.database.models import EmailDeliveryBudget, User


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EmailVerification:
    """Row locks serialize code attempts, resends and the shared mail budget."""

    def __init__(self, session, passwords, sender, settings, clock=None):
        self.session, self.passwords, self.sender, self.settings = (
            session,
            passwords,
            sender,
            settings,
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    def _user(self, email, password):
        user = self.session.scalar(
            select(User)
            .where(func.lower(User.email) == normalize_email(email))
            .with_for_update()
        )
        if (
            not self.passwords.verify(password, user.password_hash if user else None)
            or user is None
        ):
            raise InvalidCredentialsError
        if not user.is_active:
            raise InactiveUserError
        return user

    def _digest(self, user_id, code):
        key = self.settings.jwt_secret_key
        if not key:
            raise AuthenticationUnavailableError
        return hmac.new(
            key.get_secret_value().encode(),
            f"email-verification:{user_id}:{code}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def request(self, email, password):
        user = self._user(email, password)
        if user.email_verified:
            self.session.rollback()
            return {"status": "already_verified", "retry_after": 0}
        now = self.clock()
        if user.verification_sent_at:
            remaining = 60 - (now - utc(user.verification_sent_at)).total_seconds()
            if remaining > 0:
                raise VerificationRateLimitError(math.ceil(remaining))
        if not user.verification_window_start or now - utc(
            user.verification_window_start
        ) >= timedelta(hours=1):
            user.verification_window_start, user.verification_send_count = now, 0
        if user.verification_send_count >= 3:
            raise VerificationRateLimitError(
                math.ceil(
                    (
                        utc(user.verification_window_start) + timedelta(hours=1) - now
                    ).total_seconds()
                )
            )
        budget = self._reserve_mail(now)
        code = f"{secrets.randbelow(100_000_000):08d}"
        user.verification_digest = self._digest(user.id, code)
        user.verification_expires_at = now + timedelta(minutes=10)
        user.verification_attempts = 0
        user.verification_sent_at = now
        user.verification_send_count += 1
        budget.sent += 1
        budget.last_sent_at = now
        recipient = user.email
        # Reserve before calling SES. Failures/timeouts still count against spending.
        self.session.commit()
        self.sender.send_code(recipient, code)
        return {"status": "sent", "retry_after": 60}

    def confirm(self, email, password, code):
        user = self._user(email, password)
        now = self.clock()
        if (
            user.email_verified
            or not user.verification_digest
            or not user.verification_expires_at
            or utc(user.verification_expires_at) <= now
            or user.verification_attempts >= 5
        ):
            raise InvalidVerificationCodeError
        user.verification_attempts += 1
        if not hmac.compare_digest(
            user.verification_digest, self._digest(user.id, code)
        ):
            if user.verification_attempts >= 5:
                user.verification_digest = None
            self.session.commit()
            raise InvalidVerificationCodeError
        user.email_verified = True
        user.verification_digest = None
        user.verification_expires_at = None
        self.session.commit()
        return {"status": "verified"}

    def _reserve_mail(self, now):
        budget = self.session.scalar(
            select(EmailDeliveryBudget)
            .where(EmailDeliveryBudget.id == "global")
            .with_for_update()
        )
        # This row is installed by the migration; absence fails closed.
        if budget is None:
            raise AuthenticationUnavailableError
        if budget.day != now.date():
            budget.day, budget.sent = now.date(), 0
        if budget.sent >= self.settings.email_daily_limit:
            midnight = datetime.combine(
                now.date() + timedelta(days=1), datetime.min.time(), UTC
            )
            raise VerificationRateLimitError(
                math.ceil((midnight - now).total_seconds())
            )
        if budget.last_sent_at and (now - utc(budget.last_sent_at)).total_seconds() < 2:
            raise VerificationRateLimitError(2)
        return budget
