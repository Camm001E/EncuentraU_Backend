from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_email_sender
from app.domain.authentication import EmailDeliveryUnavailableError
from app.infrastructure.database.models import EmailDeliveryBudget, User
from tests.test_authentication import AUTH, PASSWORD, PAYLOAD, bearer, login, register
from tests.test_authentication import auth as auth

NEW_PASSWORD = "NuevaClaveSegura456"


class Mailbox:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_recovery_code(self, recipient, code):
        if self.fail:
            raise EmailDeliveryUnavailableError
        self.messages.append((recipient, code))

    def send_code(self, recipient, code):
        self.messages.append((recipient, code))


@pytest.fixture
def recovery(auth):
    mailbox = Mailbox()
    auth.client.app.dependency_overrides[get_email_sender] = lambda: mailbox
    with Session(auth.engine) as s:
        s.add(EmailDeliveryBudget(id="global", day=datetime.now(UTC).date(), sent=0))
        s.commit()
    register(auth)
    return auth, mailbox


def request(a, email=PAYLOAD["email"]):
    return a.client.post(f"{AUTH}/password/request", json={"email": email})


def confirm(a, code, email=PAYLOAD["email"], password=NEW_PASSWORD):
    return a.client.post(
        f"{AUTH}/password/confirm",
        json={
            "email": email,
            "code": code,
            "new_password": password,
        },
    )


def allow_resend(a):
    with Session(a.engine) as s:
        s.scalar(select(User)).recovery_sent_at = datetime.now(UTC) - timedelta(
            seconds=61
        )
        s.get(EmailDeliveryBudget, "global").last_sent_at = None
        s.commit()


def test_recovery_preserves_identity_revokes_sessions_and_code(recovery):
    a, mailbox = recovery
    before = login(a).json()
    old_token = before["access_token"]
    response = request(a)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    code = mailbox.messages[-1][1]
    assert len(code) == 8 and code not in response.text
    assert login(a).status_code == 200  # Request alone cannot lock out the owner.
    with Session(a.engine) as s:
        u = s.scalar(select(User))
        assert u.recovery_digest != code and len(u.recovery_digest) == 64
    assert confirm(a, code).json() == {"status": "password_reset"}
    assert confirm(a, code).status_code == 400
    assert login(a).status_code == 401
    assert a.client.get(f"{AUTH}/me", headers=bearer(old_token)).status_code == 401
    after = login(a, password=NEW_PASSWORD).json()
    for field in ("id", "email", "role", "student_code"):
        assert after["user"][field] == before["user"][field]
    assert (
        a.client.get(f"{AUTH}/me", headers=bearer(after["access_token"])).status_code
        == 200
    )


def test_generic_request_does_not_reveal_account_status_or_ses_failure(recovery):
    a, mailbox = recovery
    unknown = request(a, "unknown@example.com")
    existing = request(a)
    limited = request(a)
    assert unknown.json() == existing.json() == limited.json()
    assert len(mailbox.messages) == 1
    allow_resend(a)
    mailbox.fail = True
    assert request(a).json() == existing.json()
    with Session(a.engine) as s:
        assert s.get(EmailDeliveryBudget, "global").sent == 2
        s.scalar(select(User)).is_active = False
        s.commit()
    assert request(a).json() == existing.json()


def test_wrong_code_limit_and_cross_account_isolation(recovery):
    a, mailbox = recovery
    register(a, email="second@example.com", student_code="SECOND")
    request(a)
    code = mailbox.messages[-1][1]
    assert confirm(a, code, email="second@example.com").status_code == 400
    wrong = "11111111" if code != "11111111" else "22222222"
    for _ in range(6):
        assert confirm(a, wrong).status_code == 400
    assert confirm(a, code).status_code == 400
    assert login(a).status_code == 200
    with Session(a.engine) as s:
        u = s.scalar(select(User).where(User.email == PAYLOAD["email"]))
        assert u.recovery_attempts == 5 and u.recovery_digest is None


def test_expiry_replacement_and_verification_codes_are_separate(recovery):
    a, mailbox = recovery
    a.client.post(
        f"{AUTH}/verification/request",
        json={"email": PAYLOAD["email"], "password": PASSWORD},
    )
    verification = mailbox.messages[-1][1]
    allow_resend(a)
    request(a)
    code = mailbox.messages[-1][1]
    assert confirm(a, verification).status_code == 400
    allow_resend(a)
    request(a)
    second = mailbox.messages[-1][1]
    assert confirm(a, code).status_code == 400
    with Session(a.engine) as s:
        s.scalar(select(User)).recovery_expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        s.commit()
    assert confirm(a, second).status_code == 400


def test_cooldown_hourly_and_shared_daily_budget(recovery):
    a, mailbox = recovery
    request(a)
    request(a)
    assert len(mailbox.messages) == 1
    for _ in range(4):
        allow_resend(a)
        request(a)
    assert len(mailbox.messages) == 3
    with Session(a.engine) as s:
        u = s.scalar(select(User))
        u.recovery_window_start = datetime.now(UTC) - timedelta(hours=2)
        s.get(EmailDeliveryBudget, "global").sent = a.settings.email_daily_limit
        s.commit()
    allow_resend(a)
    request(a)
    assert len(mailbox.messages) == 3


@pytest.mark.parametrize("password", ["Ab7!", "x" * 129])
def test_password_policy_before_consuming_code(recovery, password):
    a, mailbox = recovery
    request(a)
    code = mailbox.messages[-1][1]
    result = confirm(a, code, password=password)
    assert result.status_code == 422
    assert password not in result.text and code not in result.text
    assert confirm(a, code).status_code == 200


def test_recovery_verifies_existing_mailbox_and_invalidates_pending_verification(
    recovery,
):
    a, mailbox = recovery
    a.settings.email_verification_required = True
    assert login(a).status_code == 403
    request(a)
    assert confirm(a, mailbox.messages[-1][1]).status_code == 200
    assert login(a, password=NEW_PASSWORD).json()["user"]["email_verified"]


def test_disabled_account_cannot_consume_valid_code(recovery):
    a, mailbox = recovery
    request(a)
    with Session(a.engine) as s:
        s.scalar(select(User)).is_active = False
        s.commit()
    assert confirm(a, mailbox.messages[-1][1]).status_code == 400


def test_reset_template_uses_recovery_instructions(monkeypatch):
    from app.core.config import Settings
    from app.infrastructure import verification_email

    sent = []

    class SES:
        def send_email(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(verification_email, "ses_client", lambda region: SES())
    settings = Settings(_env_file=None, email_sender="sender@example.com")
    verification_email.SESVerificationEmailSender(settings).send_recovery_code(
        "recipient@example.com", "12345678"
    )
    mail = sent[0]["Content"]["Simple"]
    assert "Recupera" in mail["Subject"]["Data"]
    assert "Recuperar contraseña" in mail["Body"]["Text"]["Data"]
