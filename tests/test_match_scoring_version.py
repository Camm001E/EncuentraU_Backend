from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.orm import Session

from app.domain.matching_version import CURRENT_SCORING_VERSION, LEGACY_SCORING_VERSION
from app.infrastructure.database.models import ObjectMatch
from tests.test_database_models import make_report, make_user
from tests.test_matches_postgresql import generated, pair
from tests.test_migrations import migration_config
from tests.test_reports_postgresql import reports as reports
from tests.test_reports_postgresql import reports_engine as reports_engine

pytestmark = pytest.mark.postgresql


def test_legacy_pending_is_recomputed_in_place_with_current_provenance(reports):
    lost, found = pair(reports)
    original = generated(reports, lost["id"])["items"][0]
    assert original["scoring_version"] == CURRENT_SCORING_VERSION
    with Session(reports.connection) as session:
        row = session.get(ObjectMatch, UUID(original["id"]))
        row.scoring_version = LEGACY_SCORING_VERSION
        row.percentage = 60
        row.level = "possible"
        row.factors = []
        row.warnings = ["Métricas históricas de prueba"]
        session.commit()
    updated = generated(reports, lost["id"])["items"][0]
    assert updated["id"] == original["id"]
    assert updated["created_at"] == original["created_at"]
    assert updated["updated_at"] > original["updated_at"]
    assert updated["scoring_version"] == CURRENT_SCORING_VERSION
    for name in ("percentage", "level", "factors", "warnings"):
        assert updated[name] == original[name]
    repeated = generated(reports, found["id"], mine=False)["items"][0]
    assert repeated["id"] == updated["id"]
    assert repeated["created_at"] == updated["created_at"]
    assert repeated["scoring_version"] == CURRENT_SCORING_VERSION
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectMatch)) == 1


@pytest.mark.parametrize("status", ["accepted", "rejected"])
@pytest.mark.parametrize("qualifies", [True, False])
def test_historical_final_match_keeps_metrics_and_version(reports, status, qualifies):
    lost, found = pair(reports)
    match = generated(reports, lost["id"])["items"][0]
    with Session(reports.connection) as session:
        row = session.get(ObjectMatch, UUID(match["id"]))
        row.status = status
        row.scoring_version = LEGACY_SCORING_VERSION
        session.commit()
    route = f"/api/v1/matches/{match['id']}"
    before = reports.client.get(route, headers=reports.headers).json()
    if not qualifies:
        assert (
            reports.client.patch(
                f"/api/v1/reports/{found['id']}",
                headers=reports.other_headers,
                json={"object_type": "recipiente"},
            ).status_code
            == 200
        )
    generated(reports, lost["id"])
    after = reports.client.get(route, headers=reports.headers).json()
    # Report summaries may reflect edits; all historical scoring data must not.
    for key in before.keys() - {"my_report", "candidate_report"}:
        assert after[key] == before[key]
    assert after["scoring_version"] == LEGACY_SCORING_VERSION


def test_insufficient_legacy_pending_is_pruned(reports):
    lost, found = pair(reports)
    match = generated(reports, lost["id"])["items"][0]
    with Session(reports.connection) as session:
        session.get(
            ObjectMatch, UUID(match["id"])
        ).scoring_version = LEGACY_SCORING_VERSION
        session.commit()
    assert (
        reports.client.patch(
            f"/api/v1/reports/{found['id']}",
            headers=reports.other_headers,
            json={"object_type": "recipiente"},
        ).status_code
        == 200
    )
    assert generated(reports, lost["id"])["items"] == []
    assert (
        reports.client.get(
            f"/api/v1/matches/{match['id']}", headers=reports.headers
        ).status_code
        == 404
    )


def test_version_migration_backfills_without_changing_historical_rows(reports):
    connection = reports.connection
    config = migration_config()
    config.attributes["connection"] = connection
    command.downgrade(config, "0005_delivery_closure")
    with Session(connection, expire_on_commit=False) as session:
        user = make_user()
        session.add(user)
        session.flush()
        lost = make_report(user.id)
        found = [make_report(user.id, "found") for _ in range(3)]
        session.add_all([lost, *found])
        session.commit()
    legacy = Table("object_matches", MetaData(), autoload_with=connection)
    for status, report in zip(("pending", "accepted", "rejected"), found, strict=True):
        connection.execute(
            legacy.insert().values(
                id=uuid4(),
                lost_report_id=lost.id,
                found_report_id=report.id,
                percentage=73,
                identity_percentage=66.25,
                context_percentage=100,
                evidence_coverage=92,
                compatible=True,
                level="possible",
                status=status,
                factors=[],
                warnings=[],
            )
        )
    connection.commit()
    before = [
        dict(row)
        for row in connection.execute(select(legacy).order_by(legacy.c.id)).mappings()
    ]
    command.upgrade(config, "head")
    versioned = Table("object_matches", MetaData(), autoload_with=connection)
    after = list(
        connection.execute(select(versioned).order_by(versioned.c.id)).mappings()
    )
    assert len(after) == len(before) == 3
    assert all(row["scoring_version"] == LEGACY_SCORING_VERSION for row in after)
    assert [
        {key: value for key, value in row.items() if key != "scoring_version"}
        for row in after
    ] == before
    assert not next(
        c
        for c in inspect(connection).get_columns("object_matches")
        if c["name"] == "scoring_version"
    )["nullable"]
    command.downgrade(config, "0005_delivery_closure")
    assert "scoring_version" not in {
        c["name"] for c in inspect(connection).get_columns("object_matches")
    }
    assert [
        dict(row)
        for row in connection.execute(select(legacy).order_by(legacy.c.id)).mappings()
    ] == before
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
@pytest.mark.parametrize("closed", [False, True])
def test_claim_and_closed_delivery_preserve_original_scoring_version(workflow, closed):
    with Session(workflow.engine) as session:
        session.get(
            ObjectMatch, workflow.match_id
        ).scoring_version = LEGACY_SCORING_VERSION
        session.commit()
    if closed:
        _, conversation = workflow.approved()
        delivery = workflow.client.get(
            f"/api/v1/conversations/{conversation}/delivery",
            headers=workflow.headers["A"],
        ).json()
        for actor in ("A", "B"):
            assert (
                workflow.client.post(
                    f"/api/v1/deliveries/{delivery['id']}/confirm",
                    headers=workflow.headers[actor],
                ).status_code
                == 200
            )
        assert (
            workflow.client.post(
                f"/api/v1/admin/deliveries/{delivery['id']}/complete",
                headers=workflow.headers["admin"],
            ).status_code
            == 200
        )
    else:
        assert workflow.claim().status_code == 201
    route = f"/api/v1/matches/{workflow.match_id}"
    before = workflow.client.get(route, headers=workflow.headers["A"]).json()
    response = workflow.client.post(
        f"/api/v1/reports/{workflow.lost_id}/matches/generate",
        headers=workflow.headers["A"],
    )
    assert response.status_code == (409 if closed else 200)
    assert workflow.client.get(route, headers=workflow.headers["A"]).json() == before
    assert before["scoring_version"] == LEGACY_SCORING_VERSION
