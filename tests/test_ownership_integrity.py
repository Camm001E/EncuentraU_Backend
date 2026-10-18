from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.conversations import SendMessage
from app.infrastructure.database.conversation_repository import (
    SQLAlchemyConversationRepository,
)
from app.infrastructure.database.models import (
    Conversation,
    ConversationParticipant,
    Message,
    ObjectMatch,
    ObjectReport,
    OwnershipClaim,
    User,
)
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "approved"},
        {"status": "rejected"},
        {"rejection_reason": "Motivo mientras sigue pendiente"},
        {"reviewed_at": datetime.now(UTC)},
        {"ownership_evidence": "corta"},
    ],
)
def test_claim_database_constraints(workflow, changes):
    claim_id = UUID(workflow.claim().json()["id"])
    with Session(workflow.engine) as session:
        row = session.get(OwnershipClaim, claim_id)
        for key, value in changes.items():
            setattr(row, key, value)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_different_claim_participants_constraint(workflow):
    claim_id = UUID(workflow.claim().json()["id"])
    with Session(workflow.engine) as session:
        row = session.get(OwnershipClaim, claim_id)
        row.custodian_user_id = row.claimant_user_id
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_only_registered_participants_can_exist_as_message_senders(workflow):
    _, conversation = workflow.approved()
    with Session(workflow.engine) as session:
        session.add(
            Message(
                conversation_id=UUID(conversation),
                sender_id=workflow.ids["C"],
                body="No debe persistir",
                client_message_id=uuid4(),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Message)) == 0


def test_approved_claim_cannot_have_rejection_reason(workflow):
    claim, _ = workflow.approved()
    with Session(workflow.engine) as session:
        session.get(
            OwnershipClaim, UUID(claim)
        ).rejection_reason = "Motivo incompatible"
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_participant_cannot_review_own_claim_even_after_admin_promotion(workflow):
    claim_id = workflow.claim().json()["id"]
    with Session(workflow.engine) as session:
        session.get(User, workflow.ids["A"]).role = "admin"
        session.commit()
    response = workflow.client.post(
        f"/api/v1/admin/claims/{claim_id}/approve", headers=workflow.headers["A"]
    )
    assert response.status_code == 403


@pytest.mark.parametrize("report_id", ["lost_id", "found_id"])
def test_approval_rechecks_report_activity(workflow, report_id):
    claim_id = workflow.claim().json()["id"]
    with Session(workflow.engine) as session:
        session.get(ObjectReport, getattr(workflow, report_id)).status = "cancelled"
        session.commit()
    assert workflow.approve(claim_id).status_code == 409
    with Session(workflow.engine) as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0


def test_admin_queue_does_not_send_private_answers(workflow):
    workflow.claim()
    body = workflow.client.get(
        "/api/v1/admin/claims", headers=workflow.headers["admin"]
    ).json()
    assert body["total"] == 1
    assert not {
        "ownership_evidence",
        "lost_private_feature",
        "found_private_feature",
        "admin_note",
    }.intersection(body["items"][0])


def test_read_watermark_does_not_move_backwards(workflow):
    _, conversation = workflow.approved()
    messages = []
    for i in range(2):
        response = workflow.client.post(
            f"/api/v1/conversations/{conversation}/messages",
            json={"body": f"Mensaje {i}", "client_message_id": str(uuid4())},
            headers=workflow.headers["A"],
        )
        messages.append(response.json()["id"])
    for identifier in reversed(messages):
        assert (
            workflow.client.post(
                f"/api/v1/conversations/{conversation}/read",
                json={"last_message_id": identifier},
                headers=workflow.headers["B"],
            ).status_code
            == 204
        )
    assert (
        workflow.client.get(
            f"/api/v1/conversations/{conversation}", headers=workflow.headers["B"]
        ).json()["unread_count"]
        == 0
    )


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
def test_concurrent_message_retries_persist_once(workflow):
    _, conversation = workflow.approved()
    identifier = uuid4()

    def send(_):
        with Session(workflow.engine, expire_on_commit=False) as session:
            user = SQLAlchemyUserRepository(session).get_by_id(workflow.ids["A"])
            return SendMessage(SQLAlchemyConversationRepository(session))(
                UUID(conversation), user, "Texto de prueba concurrente", identifier
            ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert results[0] == results[1]
    with Session(workflow.engine) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
def test_generation_retains_pending_claim_and_its_metrics(workflow):
    claim_id = workflow.claim().json()["id"]
    before = workflow.client.get(
        f"/api/v1/claims/{claim_id}", headers=workflow.headers["A"]
    ).json()["match"]
    with Session(workflow.engine) as session:
        session.get(
            ObjectReport, workflow.found_id
        ).object_type = "calculadora científica"
        session.commit()
    generated = workflow.client.post(
        f"/api/v1/reports/{workflow.lost_id}/matches/generate",
        headers=workflow.headers["A"],
    )
    assert generated.status_code == 200
    with Session(workflow.engine) as session:
        match = session.get(ObjectMatch, workflow.match_id)
        assert match is not None and match.percentage == before["percentage"]
        assert session.get(OwnershipClaim, UUID(claim_id)).status == "pending"
        assert (
            session.scalar(select(func.count()).select_from(ConversationParticipant))
            == 0
        )
