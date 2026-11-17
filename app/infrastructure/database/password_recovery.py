"""Independent recovery codes; locks protect attempts, consumption and mail budget."""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.domain.authentication import (
    AuthenticationError,
    InvalidVerificationCodeError,
    VerificationRateLimitError,
)
from app.domain.users import normalize_email
from app.infrastructure.database import session as database_session
from app.infrastructure.database.email_verification import EmailVerification, utc
from app.infrastructure.database.models import User


class PasswordRecovery(EmailVerification):
    def _digest(self, user_id, code):
        return hmac.new(
            self.settings.jwt_secret_key.get_secret_value().encode(),
            f"password-recovery:{user_id}:{code}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _find(self, email):
        return self.session.scalar(
            select(User)
            .where(func.lower(User.email) == normalize_email(email))
            .with_for_update()
        )

    def request(self, email):
        user = self._find(email)
        if user is None or not user.is_active:
            return
        now = self.clock()
        if user.recovery_sent_at and now - utc(user.recovery_sent_at) < timedelta(
            seconds=60
        ):
            return
        if not user.recovery_window_start or now - utc(
            user.recovery_window_start
        ) >= timedelta(hours=1):
            user.recovery_window_start, user.recovery_send_count = now, 0
        if user.recovery_send_count >= 3:
            return
        try:
            budget = self._reserve_mail(now)
        except VerificationRateLimitError:
            return
        code = f"{secrets.randbelow(100_000_000):08d}"
        user.recovery_digest = self._digest(user.id, code)
        user.recovery_expires_at = now + timedelta(minutes=10)
        user.recovery_attempts = 0
        user.recovery_sent_at = now
        user.recovery_send_count += 1
        budget.sent += 1
        budget.last_sent_at = now
        recipient = user.email
        self.session.commit()
        self.sender.send_recovery_code(recipient, code)

    def confirm(self, email, code, password):
        user = self._find(email)
        if (
            user is None
            or not user.is_active
            or not user.recovery_digest
            or not user.recovery_expires_at
            or utc(user.recovery_expires_at) <= self.clock()
            or user.recovery_attempts >= 5
        ):
            raise InvalidVerificationCodeError
        user.recovery_attempts += 1
        if not hmac.compare_digest(user.recovery_digest, self._digest(user.id, code)):
            if user.recovery_attempts >= 5:
                user.recovery_digest = None
            self.session.commit()
            raise InvalidVerificationCodeError
        user.password_hash = self.passwords.hash(password)
        user.session_version += 1
        user.recovery_digest = None
        user.recovery_expires_at = None
        # A recovery code also proves access to the account's existing mailbox.
        user.email_verified = True
        user.verification_digest = None
        user.verification_expires_at = None
        self.session.commit()
        return {"status": "password_reset"}


def send_recovery_in_background(email, passwords, sender, settings):
    # Separate session: request dependencies may already have been closed.
    # Delivery happens after the generic response, avoiding an SES timing oracle.
    try:
        with database_session.get_session_factory()() as session:
            PasswordRecovery(session, passwords, sender, settings).request(email)
    except (AuthenticationError, SQLAlchemyError):
        logging.getLogger(__name__).warning("Password recovery delivery unavailable")
