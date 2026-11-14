from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_email_sender
from app.domain.authentication import EmailDeliveryUnavailableError
from app.infrastructure.database.models import EmailDeliveryBudget, User
from tests.test_authentication import (
    AUTH,
    PASSWORD,
    PAYLOAD,
    bearer,
    login,
    register,
)
from tests.test_authentication import (
    auth as auth,
)


class Mailbox:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_code(self, recipient, code):
        if self.fail:
            raise EmailDeliveryUnavailableError
        self.messages.append((recipient, code))


@pytest.fixture
def verified_app(auth):
    auth.settings.email_verification_required = True
    mailbox = Mailbox()
    auth.client.app.dependency_overrides[get_email_sender] = lambda: mailbox
    with Session(auth.engine) as s:
        s.add(EmailDeliveryBudget(id="global", day=datetime.now(UTC).date(), sent=0))
        s.commit()
    return auth, mailbox


def request(a, **kwargs):
    return a.client.post(
        f"{AUTH}/verification/request",
        json={"email": PAYLOAD["email"], "password": PASSWORD, **kwargs},
    )


def confirm(a, code, **kwargs):
    return a.client.post(
        f"{AUTH}/verification/confirm",
        json={"email": PAYLOAD["email"], "password": PASSWORD, "code": code, **kwargs},
    )


def allow_resend(a):
    with Session(a.engine) as s:
        u = s.scalar(select(User))
        u.verification_sent_at = datetime.now(UTC) - timedelta(seconds=61)
        s.get(EmailDeliveryBudget, "global").last_sent_at = None
        s.commit()


def test_register_verify_login_single_use_no_code_leaks(verified_app):
    a, mailbox = verified_app
    r = register(a)
    assert r.status_code == 201 and r.json()["email_verification_required"]
    assert not r.json()["email_verified"]
    assert login(a).json()["code"] == "email_verification_required"
    r = request(a)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    code = mailbox.messages[-1][1]
    assert len(code) == 8 and code not in r.text
    with Session(a.engine) as s:
        u = s.scalar(select(User))
        assert u.verification_digest != code and len(u.verification_digest) == 64
    assert confirm(a, code).status_code == 200
    assert confirm(a, code).status_code == 400
    logged = login(a)
    assert logged.status_code == 200 and logged.json()["user"]["email_verified"]
    assert request(a).json()["status"] == "already_verified"
    assert len(mailbox.messages) == 1


def test_existing_token_cannot_bypass_verification(verified_app):
    a, _ = verified_app
    a.settings.email_verification_required = False
    register(a)
    token = login(a).json()["access_token"]
    a.settings.email_verification_required = True
    r = a.client.get(f"{AUTH}/me", headers=bearer(token))
    assert r.status_code == 403 and r.json()["code"] == "email_verification_required"


def test_wrong_password_and_inactive_user_cannot_send(verified_app):
    a, mailbox = verified_app
    register(a)
    assert request(a, password="wrong").status_code == 401
    assert request(a, email="absent@example.com").status_code == 401
    with Session(a.engine) as s:
        s.scalar(select(User)).is_active = False
        s.commit()
    assert request(a).status_code == 403
    assert not mailbox.messages


def test_attempt_limit_expiry_and_replacement(verified_app):
    a, mailbox = verified_app
    register(a)
    request(a)
    first = mailbox.messages[-1][1]
    wrong = "00000000" if first != "00000000" else "11111111"
    for _ in range(5):
        assert confirm(a, wrong).status_code == 400
    assert confirm(a, first).status_code == 400
    allow_resend(a)
    assert request(a).status_code == 200
    second = mailbox.messages[-1][1]
    assert confirm(a, first).status_code == 400
    with Session(a.engine) as s:
        s.scalar(select(User)).verification_expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        s.commit()
    assert confirm(a, second).status_code == 400
    assert login(a).status_code == 403


def test_cooldown_hourly_and_shared_daily_limits(verified_app):
    a, mailbox = verified_app
    register(a)
    assert request(a).status_code == 200
    assert request(a).status_code == 429
    for _ in range(2):
        allow_resend(a)
        assert request(a).status_code == 200
    allow_resend(a)
    assert request(a).status_code == 429
    with Session(a.engine) as s:
        s.scalar(select(User)).verification_window_start = datetime.now(
            UTC
        ) - timedelta(hours=2)
        s.get(EmailDeliveryBudget, "global").sent = a.settings.email_daily_limit
        s.commit()
    assert request(a).status_code == 429
    assert len(mailbox.messages) == 3


def test_send_failure_keeps_account_and_reserves_budget(verified_app):
    a, mailbox = verified_app
    register(a)
    mailbox.fail = True
    assert request(a).status_code == 503
    assert request(a).status_code == 429
    with Session(a.engine) as s:
        assert s.get(EmailDeliveryBudget, "global").sent == 1
        assert not s.scalar(select(User)).email_verified


def test_validation_does_not_echo_password_or_code(verified_app):
    a, _ = verified_app
    register(a)
    r = confirm(a, "private-invalid-code")
    assert r.status_code == 422
    assert PASSWORD not in r.text and "private-invalid-code" not in r.text
