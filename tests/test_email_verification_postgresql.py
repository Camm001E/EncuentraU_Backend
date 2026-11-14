import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.authentication import (
    InvalidVerificationCodeError,
    VerificationRateLimitError,
)
from app.infrastructure.database.base import Base
from app.infrastructure.database.email_verification import EmailVerification
from app.infrastructure.database.models import EmailDeliveryBudget, User


class Passwords:
    def verify(self, password, digest):
        return password == "test-password" and digest == "test-hash"


class Mailbox:
    code = None

    def send_code(self, recipient, code):
        self.code = code


@pytest.fixture
def pg_email():
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Isolated PostgreSQL required")
    assert "_test" in make_url(raw).database
    schema = "email_test_" + uuid4().hex
    control = create_engine(raw)
    with control.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    engine = create_engine(raw, connect_args={"options": "-csearch_path=" + schema})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(
            User(
                id=uuid4(),
                full_name="Test",
                email="test@example.com",
                student_code="TEST",
                password_hash="test-hash",
            )
        )
        s.add(EmailDeliveryBudget(id="global", day=datetime.now(UTC).date(), sent=0))
        s.commit()
    settings = Settings(_env_file=None, jwt_secret_key="a" * 64)
    mailbox = Mailbox()
    try:
        yield engine, settings, mailbox
    finally:
        engine.dispose()
        with control.begin() as c:
            c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        control.dispose()


def test_concurrent_resend_and_single_consumption(pg_email):
    engine, settings, mailbox = pg_email

    def send(_):
        with Session(engine) as s:
            try:
                EmailVerification(s, Passwords(), mailbox, settings).request(
                    "test@example.com", "test-password"
                )
                return "sent"
            except VerificationRateLimitError:
                return "limited"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, range(4)))
    assert results.count("sent") == 1 and results.count("limited") == 3

    def confirm(_):
        with Session(engine) as s:
            try:
                EmailVerification(s, Passwords(), mailbox, settings).confirm(
                    "test@example.com", "test-password", mailbox.code
                )
                return "verified"
            except InvalidVerificationCodeError:
                return "consumed"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(confirm, range(4)))
    assert results.count("verified") == 1 and results.count("consumed") == 3
    with Session(engine) as s:
        assert s.get(EmailDeliveryBudget, "global").sent == 1


def test_concurrent_wrong_guesses_persist_five_attempt_limit(pg_email):
    engine, settings, mailbox = pg_email
    with Session(engine) as s:
        EmailVerification(s, Passwords(), mailbox, settings).request(
            "test@example.com", "test-password"
        )
    wrong = "00000000" if mailbox.code != "00000000" else "11111111"

    def guess(_):
        with Session(engine) as s:
            with pytest.raises(InvalidVerificationCodeError):
                EmailVerification(s, Passwords(), mailbox, settings).confirm(
                    "test@example.com", "test-password", wrong
                )

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(guess, range(8)))
    with Session(engine) as s:
        user = s.scalar(select(User))
        assert user.verification_attempts == 5 and user.verification_digest is None
        assert not user.email_verified
