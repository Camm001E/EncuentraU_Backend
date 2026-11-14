import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.database.models import ObjectReport
from tests.test_deliveries import approved, call, complete, confirm


def test_hidden_closed_case_keeps_chat_and_object_context(workflow):
    delivery, _, conversation = approved(workflow)
    confirm(workflow, delivery, "A")
    confirm(workflow, delivery, "B")
    assert complete(workflow, delivery).status_code == 200
    before_chat = call(workflow, "get", f"conversations/{conversation}").json()
    before_match = call(workflow, "get", f"matches/{workflow.match_id}").json()
    with Session(workflow.engine) as session:
        for rid in (workflow.lost_id, workflow.found_id):
            session.get(ObjectReport, rid).hidden_from_lists = True
        session.commit()
    for actor, rid in (("A", workflow.lost_id), ("B", workflow.found_id)):
        assert call(workflow, "get", "reports/me", actor).json()["total"] == 0
        assert call(workflow, "get", "matches/me", actor).json()["total"] == 0
        assert (
            call(workflow, "get", f"matches/me?report_id={rid}", actor).json()["total"]
            == 0
        )
        assert call(workflow, "get", f"reports/{rid}", actor).status_code == 200
        assert (
            call(workflow, "get", f"conversations/{conversation}", actor).status_code
            == 200
        )
    assert call(workflow, "get", f"conversations/{conversation}").json() == before_chat
    assert call(workflow, "get", f"matches/{workflow.match_id}").json() == before_match
    assert (
        call(workflow, "get", f"conversations/{conversation}", "C").status_code == 404
    )


def test_active_report_cannot_be_hidden(workflow):
    if workflow.engine.dialect.name != "postgresql":
        pytest.skip("Production database constraint requires PostgreSQL")
    with Session(workflow.engine) as session:
        row = session.scalar(
            select(ObjectReport).where(ObjectReport.id == workflow.lost_id)
        )
        row.hidden_from_lists = True
        with pytest.raises(IntegrityError):
            session.commit()
