import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies.object_matches import get_matching_service
from app.application.matching_service import MatchingService
from app.application.object_matches import GenerateReportMatches
from app.domain.matching import MatchRequest
from app.infrastructure.database.models import (
    ImageAnalysis,
    ObjectMatch,
    ObjectReport,
    User,
)
from app.infrastructure.database.object_match_repository import (
    SQLAlchemyObjectMatchRepository,
)
from app.infrastructure.gemini_image_analyzer import GeminiImageAnalyzer
from tests.test_database_models import make_user
from tests.test_migrations import migration_config
from tests.test_reports_postgresql import (
    reports as reports,
)
from tests.test_reports_postgresql import (
    reports_engine as reports_engine,
)

pytestmark = pytest.mark.postgresql
MATCHES = "/api/v1/matches"
REPORTS = "/api/v1/reports"
FIXTURES = Path(__file__).parent / "fixtures" / "matching"


@pytest.fixture(autouse=True)
def no_new_gemini_calls(monkeypatch):
    analyzer = Mock(
        side_effect=AssertionError(
            "No se debe invocar Gemini al generar coincidencias."
        )
    )
    monkeypatch.setattr(GeminiImageAnalyzer, "analyze", analyzer)
    yield
    analyzer.assert_not_called()


def saved_request(case="same_object"):
    return json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))


def create_report(
    reports, side, *, case="same_object", mine=True, with_analysis=True, **changes
):
    values = saved_request(case)[side]
    visual = {name: values.pop(name) for name in ("visible_features", "visible_text")}
    body = {
        **values,
        "report_type": side,
        "event_date": (date.today() - timedelta(days=1)).isoformat(),
        "private_feature": "Privado del propietario: nunca publicar en matching",
        **changes,
    }
    if with_analysis:
        body["analysis"] = {"extracted_data": visual, "confidence": "alta"}
    response = reports.client.post(
        REPORTS, headers=reports.headers if mine else reports.other_headers, json=body
    )
    assert response.status_code == 201, response.json()
    return response.json()


def pair(reports, case="same_object", *, with_analysis=True):
    return (
        create_report(reports, "lost", case=case, with_analysis=with_analysis),
        create_report(
            reports, "found", case=case, mine=False, with_analysis=with_analysis
        ),
    )


def generate(reports, report_id, *, mine=True):
    return reports.client.post(
        f"{REPORTS}/{report_id}/matches/generate",
        headers=reports.headers if mine else reports.other_headers,
    )


def generated(reports, report_id, *, mine=True):
    response = generate(reports, report_id, mine=mine)
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.parametrize(
    "case,level", [("same_object", "high"), ("similar_object", "possible")]
)
@pytest.mark.parametrize("from_found", [False, True])
def test_real_matching_persists_qualified_pairs_in_canonical_order(
    reports, case, level, from_found
):
    lost, found = pair(reports, case)
    source = found if from_found else lost
    response = generated(reports, source["id"], mine=not from_found)
    assert response["report_id"] == source["id"] and response["total"] == 1
    match = response["items"][0]
    assert match["level"] == level and match["compatible"] is True
    assert match["percentage"] >= (85 if level == "high" else 60)
    if level == "possible":
        assert match["percentage"] < 85
    expected_request = saved_request(case)
    for value in expected_request.values():
        value["event_date"] = lost["event_date"]
    expected = MatchingService().evaluate(MatchRequest.model_validate(expected_request))
    assert {
        key: match[key] for key in type(expected).model_fields
    } == expected.model_dump(mode="json")
    assert match["my_report"]["id"] == source["id"]
    assert match["status"] == "pending" and match["updated_at"] == match["created_at"]
    with Session(reports.connection) as session:
        row = session.get(ObjectMatch, UUID(match["id"]))
        assert str(row.lost_report_id) == lost["id"]
        assert str(row.found_report_id) == found["id"]
        assert row.percentage == expected.percentage
        assert row.factors == expected.model_dump(mode="json")["factors"]


def test_incompatible_object_is_not_persisted(reports):
    lost, _ = pair(reports, "different_object")
    assert generated(reports, lost["id"])["items"] == []
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectMatch)) == 0


def test_compatible_but_low_object_is_not_persisted(reports):
    lost, found = pair(reports)
    changes = {
        "primary_color": "blanco",
        "secondary_colors": ["rojo"],
        "shape": "rectangular",
        "brand": "Otra marca",
        "category": "otro",
        "description": "Producto de características completamente distintas",
        "location": "Biblioteca",
    }
    assert (
        reports.client.patch(
            f"{REPORTS}/{found['id']}", headers=reports.other_headers, json=changes
        ).status_code
        == 200
    )
    assert generated(reports, lost["id"])["items"] == []


@pytest.mark.parametrize(
    "invalid",
    ["same_owner", "same_type", "cancelled", "resolved", "earlier", "too_late"],
)
@pytest.mark.parametrize("from_found", [False, True])
def test_generation_excludes_ineligible_candidates_before_evaluation(
    reports, invalid, from_found
):
    source_type, other_type = ("found", "lost") if from_found else ("lost", "found")
    source_date = date.today() - timedelta(days=20)
    source = create_report(reports, source_type, event_date=source_date.isoformat())
    changes = {"event_date": source_date.isoformat()}
    if invalid == "earlier":
        changes["event_date"] = (
            source_date + timedelta(days=1 if from_found else -1)
        ).isoformat()
    elif invalid == "too_late":
        changes["event_date"] = (
            source_date + timedelta(days=-15 if from_found else 15)
        ).isoformat()
    candidate = create_report(
        reports,
        source_type if invalid == "same_type" else other_type,
        mine=invalid == "same_owner",
        **changes,
    )
    if invalid in {"cancelled", "resolved"}:
        assert (
            reports.client.patch(
                f"{REPORTS}/{candidate['id']}",
                headers=reports.other_headers,
                json={"status": invalid},
            ).status_code
            == 200
        )
    matching = Mock(wraps=MatchingService())
    reports.client.app.dependency_overrides[get_matching_service] = lambda: matching
    assert generated(reports, source["id"])["total"] == 0
    matching.evaluate.assert_not_called()


@pytest.mark.parametrize("days", [0, 14])
def test_temporal_boundaries_are_inclusive(reports, days):
    lost = create_report(
        reports, "lost", event_date=(date.today() - timedelta(days=14)).isoformat()
    )
    create_report(
        reports,
        "found",
        mine=False,
        event_date=(date.today() - timedelta(days=14 - days)).isoformat(),
    )
    assert generated(reports, lost["id"])["total"] == 1


def test_reports_without_image_analysis_still_match(reports):
    lost, _ = pair(reports, with_analysis=False)
    match = generated(reports, lost["id"])["items"][0]
    assert match["level"] == "high"
    visual = next(
        factor for factor in match["factors"] if factor["name"] == "visual_features"
    )
    assert visual["status"] == "unknown"


def test_repeated_generation_is_idempotent_from_both_sides(reports):
    lost, found = pair(reports)
    first = generated(reports, lost["id"])["items"][0]
    second = generated(reports, lost["id"])["items"][0]
    third = generated(reports, found["id"], mine=False)["items"][0]
    assert first["id"] == second["id"] == third["id"]
    assert first["created_at"] == second["created_at"] == third["created_at"]
    assert second["updated_at"] > first["updated_at"]
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectMatch)) == 1


def test_pending_match_updates_metrics_factors_warnings_and_keeps_identity(reports):
    lost, found = pair(reports)
    original = generated(reports, lost["id"])["items"][0]
    assert (
        reports.client.patch(
            f"{REPORTS}/{found['id']}",
            headers=reports.other_headers,
            json={"secondary_colors": ["rojo"]},
        ).status_code
        == 200
    )
    updated = generated(reports, lost["id"])["items"][0]
    assert (
        updated["id"] == original["id"]
        and updated["created_at"] == original["created_at"]
    )
    assert updated["updated_at"] > original["updated_at"]
    assert updated["percentage"] < original["percentage"]
    assert updated["factors"] != original["factors"]
    assert updated["warnings"] != original["warnings"]


@pytest.mark.parametrize(
    "reason", ["incompatible", "cancelled", "resolved", "date", "low"]
)
def test_pending_matches_are_pruned_when_no_longer_qualified(reports, reason):
    lost, found = pair(reports)
    original = generated(reports, lost["id"])["items"][0]
    changes = {
        "incompatible": {"object_type": "calculadora"},
        "cancelled": {"status": "cancelled"},
        "resolved": {"status": "resolved"},
        "date": {"event_date": (date.today() - timedelta(days=2)).isoformat()},
        "low": {
            "category": "otro",
            "primary_color": "blanco",
            "secondary_colors": ["rojo"],
            "shape": "rectangular",
            "brand": "Otra marca",
            "location": "Biblioteca",
            "description": "Producto diferente sin rasgos comunes",
        },
    }[reason]
    assert (
        reports.client.patch(
            f"{REPORTS}/{found['id']}", headers=reports.other_headers, json=changes
        ).status_code
        == 200
    )
    assert generated(reports, lost["id"])["items"] == []
    with Session(reports.connection) as session:
        assert session.get(ObjectMatch, UUID(original["id"])) is None


@pytest.mark.parametrize("status", ["accepted", "rejected"])
@pytest.mark.parametrize("still_qualifies", [True, False])
def test_final_matches_are_never_updated_or_deleted(reports, status, still_qualifies):
    lost, found = pair(reports)
    original = generated(reports, lost["id"])["items"][0]
    with Session(reports.connection) as session:
        session.get(ObjectMatch, UUID(original["id"])).status = status
        session.commit()
    protected = reports.client.get(
        f"{MATCHES}/{original['id']}", headers=reports.headers
    ).json()
    changes = (
        {"secondary_colors": ["rojo"]}
        if still_qualifies
        else {"object_type": "calculadora"}
    )
    assert (
        reports.client.patch(
            f"{REPORTS}/{found['id']}", headers=reports.other_headers, json=changes
        ).status_code
        == 200
    )
    preserved = generated(reports, lost["id"])["items"][0]
    for key in (
        "id",
        "percentage",
        "identity_percentage",
        "context_percentage",
        "evidence_coverage",
        "compatible",
        "level",
        "status",
        "factors",
        "warnings",
        "created_at",
        "updated_at",
    ):
        assert preserved[key] == protected[key]


@pytest.mark.parametrize("status", ["cancelled", "resolved"])
def test_non_active_source_returns_conflict_without_deleting_matches(reports, status):
    lost, _ = pair(reports)
    generated(reports, lost["id"])
    assert (
        reports.client.patch(
            f"{REPORTS}/{lost['id']}", headers=reports.headers, json={"status": status}
        ).status_code
        == 200
    )
    assert generate(reports, lost["id"]).status_code == 409
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectMatch)) == 1


@pytest.mark.parametrize("exists", [False, True])
def test_generation_is_owner_only_and_does_not_reveal_report_existence(reports, exists):
    report_id = (
        create_report(reports, "lost", mine=False)["id"] if exists else str(uuid4())
    )
    response = generate(reports, report_id)
    assert response.status_code == 404
    assert response.json() == {"detail": "Reporte no encontrado."}


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", f"{REPORTS}/{uuid4()}/matches/generate"),
        ("get", f"{MATCHES}/me"),
        ("get", f"{MATCHES}/{uuid4()}"),
    ],
)
@pytest.mark.parametrize("token", ["missing", "invalid", "inactive"])
def test_match_routes_require_valid_jwt_and_active_user(reports, method, path, token):
    headers = {}
    if token == "invalid":
        headers = {"Authorization": "Bearer not-a-valid-token"}
    elif token == "inactive":
        with Session(reports.connection) as session:
            session.get(User, reports.user_id).is_active = False
            session.commit()
        headers = reports.headers
    response = reports.client.request(method, path, headers=headers)
    assert response.status_code == (403 if token == "inactive" else 401)
    if token != "inactive":
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_participants_see_own_oriented_summaries_without_private_or_personal_data(
    reports,
):
    lost, found = pair(reports)
    created = generated(reports, lost["id"])["items"][0]
    for headers, my_id, other_id in [
        (reports.headers, lost["id"], found["id"]),
        (reports.other_headers, found["id"], lost["id"]),
    ]:
        detail = reports.client.get(f"{MATCHES}/{created['id']}", headers=headers)
        assert detail.status_code == 200
        body = detail.json()
        assert (
            body["my_report"]["id"] == my_id
            and body["candidate_report"]["id"] == other_id
        )
        page = reports.client.get(f"{MATCHES}/me", headers=headers).json()
        assert page["items"] == [body]

        def assert_safe(value):
            if isinstance(value, dict):
                assert not value.keys() & {
                    "private_feature",
                    "user_id",
                    "email",
                    "student_code",
                    "password",
                    "password_hash",
                    "extracted_data",
                    "analysis",
                }
                for item in value.values():
                    assert_safe(item)
            elif isinstance(value, list):
                for item in value:
                    assert_safe(item)

        assert_safe(body)
        assert lost["private_feature"] not in detail.text
        assert str(reports.other_user_id) not in detail.text


def test_list_and_detail_hide_matches_between_unrelated_users(reports):
    lost, found = pair(reports)
    created = generated(reports, lost["id"])["items"][0]
    with Session(reports.connection) as session:
        third = make_user()
        session.add(third)
        session.flush()
        third_id = third.id
        # Remove this user's participation without changing the stored pair.
        session.get(ObjectReport, UUID(lost["id"])).user_id = third_id
        session.commit()
    page = reports.client.get(f"{MATCHES}/me", headers=reports.headers).json()
    assert page["items"] == [] and page["total"] == 0
    for match_id in [created["id"], str(uuid4())]:
        response = reports.client.get(f"{MATCHES}/{match_id}", headers=reports.headers)
        assert response.status_code == 404 and response.json() == {
            "detail": "Coincidencia no encontrada."
        }


def test_pagination_filters_and_percentage_date_ordering(reports):
    lost = create_report(reports, "lost")
    for case in ["same_object", "similar_object", "same_object"]:
        create_report(reports, "found", case=case, mine=False)
    all_items = generated(reports, lost["id"])["items"]
    assert len(all_items) == 3
    assert [item["percentage"] for item in all_items] == sorted(
        [item["percentage"] for item in all_items], reverse=True
    )
    with Session(reports.connection) as session:
        session.get(ObjectMatch, UUID(all_items[0]["id"])).status = "accepted"
        session.commit()
    page = reports.client.get(
        f"{MATCHES}/me?limit=1&offset=1", headers=reports.headers
    ).json()
    assert (page["total"], page["limit"], page["offset"]) == (3, 1, 1)
    assert page["items"][0]["id"] == all_items[1]["id"]
    possible = reports.client.get(
        f"{MATCHES}/me?level=possible&status=pending", headers=reports.headers
    ).json()
    assert possible["total"] == 1 and possible["items"][0]["level"] == "possible"
    accepted = reports.client.get(
        f"{MATCHES}/me?status=accepted", headers=reports.headers
    ).json()
    assert accepted["total"] == 1 and accepted["items"][0]["id"] == all_items[0]["id"]
    empty = reports.client.get(
        f"{MATCHES}/me?offset=100", headers=reports.headers
    ).json()
    assert empty["total"] == 3 and empty["items"] == []


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "level=invalid", "status=invalid"]
)
def test_invalid_match_filters_return_422_without_echoing_inputs(reports, query):
    response = reports.client.get(f"{MATCHES}/me?{query}", headers=reports.headers)
    assert response.status_code == 422 and '"input"' not in response.text


def test_latest_analysis_is_selected_without_query_per_candidate(reports):
    lost, _ = pair(reports)
    for _ in range(3):
        create_report(reports, "found", mine=False)
    with Session(reports.connection) as session:
        session.add(
            ImageAnalysis(
                report_id=UUID(lost["id"]),
                provider="gemini",
                model="newer",
                extracted_data={"visible_features": ["nuevo rasgo"]},
                confidence="alta",
            )
        )
        session.commit()
    captured = []

    class CaptureMatching(MatchingService):
        def evaluate(self, request):
            assert request.lost.visible_features == ["nuevo rasgo"]
            captured.append(request)
            return super().evaluate(request)

    reports.client.app.dependency_overrides[get_matching_service] = CaptureMatching
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "image_analyses" in statement
        ):
            statements.append(statement)

    event.listen(reports.engine, "before_cursor_execute", capture)
    try:
        generated(reports, lost["id"])
    finally:
        event.remove(reports.engine, "before_cursor_execute", capture)
    assert len(captured) == 4
    assert len(statements) == 2  # One for source; one batched query for all candidates.


def test_generation_failure_rolls_back_upserts_and_cleanup(reports, monkeypatch):
    lost, found = pair(reports)
    original = generated(reports, lost["id"])["items"][0]
    create_report(reports, "found", mine=False)
    assert (
        reports.client.patch(
            f"{REPORTS}/{found['id']}",
            headers=reports.other_headers,
            json={"object_type": "calculadora"},
        ).status_code
        == 200
    )
    synchronize = SQLAlchemyObjectMatchRepository.synchronize

    def fail_after_writes(repository, *args):
        synchronize(repository, *args)
        raise SQLAlchemyError("internal-details-must-not-leak")

    monkeypatch.setattr(
        SQLAlchemyObjectMatchRepository, "synchronize", fail_after_writes
    )
    response = generate(reports, lost["id"])
    assert response.status_code == 503 and "internal-details" not in response.text
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectMatch)) == 1
        assert session.get(ObjectMatch, UUID(original["id"])) is not None


def test_concurrent_generation_from_opposite_sides_preserves_unique_pair(reports):
    lost, found = pair(reports)
    schema = reports.connection.scalar(text("SELECT current_schema()"))
    reports.connection.commit()
    barrier = Barrier(2)

    def run(report_id, owner_id):
        with reports.engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            with Session(connection) as session:
                barrier.wait(timeout=10)
                result = GenerateReportMatches(
                    SQLAlchemyObjectMatchRepository(session), MatchingService()
                )(UUID(report_id), owner_id)
                return result.items[0].id

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run, lost["id"], reports.user_id)
        second = executor.submit(run, found["id"], reports.other_user_id)
        assert first.result(timeout=20) == second.result(timeout=20)
    with Session(reports.connection) as session:
        assert session.scalar(select(func.count()).select_from(ObjectMatch)) == 1


def test_timestamp_migration_preserves_existing_rows_and_schema_matches(reports):
    lost, found = pair(reports)
    original = generated(reports, lost["id"])["items"][0]
    config = migration_config()
    config.attributes["connection"] = reports.connection
    command.downgrade(config, "0001_postgresql_foundation")
    command.upgrade(config, "head")
    reports.connection.commit()
    with Session(reports.connection) as session:
        row = session.get(ObjectMatch, UUID(original["id"]))
        assert row.updated_at == row.created_at
        assert (
            str(row.lost_report_id) == lost["id"]
            and str(row.found_report_id) == found["id"]
        )
        assert session.scalar(select(func.count()).select_from(User)) == 2
    command.check(config)


def test_pruning_pending_pairs_does_not_touch_other_source_reports(reports):
    lost, found = pair(reports)
    generated(reports, lost["id"])
    other_lost = create_report(reports, "lost")
    protected = generated(reports, other_lost["id"])["items"][0]
    assert (
        reports.client.patch(
            f"{REPORTS}/{found['id']}",
            headers=reports.other_headers,
            json={"object_type": "calculadora"},
        ).status_code
        == 200
    )
    assert generated(reports, lost["id"])["items"] == []
    with Session(reports.connection) as session:
        remaining = session.scalars(select(ObjectMatch)).all()
        assert len(remaining) == 1 and str(remaining[0].id) == protected["id"]


def test_every_match_request_uses_one_session_and_closes_it(reports):
    lost, _ = pair(reports)
    before = len(reports.sessions)
    match = generated(reports, lost["id"])["items"][0]
    assert len(reports.sessions) == before + 1
    assert (
        reports.client.get(f"{MATCHES}/me", headers=reports.headers).status_code == 200
    )
    assert len(reports.sessions) == before + 2
    assert (
        reports.client.get(
            f"{MATCHES}/{match['id']}", headers=reports.headers
        ).status_code
        == 200
    )
    assert len(reports.sessions) == before + 3
    assert generate(reports, str(uuid4())).status_code == 404
    assert len(reports.sessions) == before + 4
    assert all(not session.in_transaction() for session in reports.sessions)


@pytest.mark.parametrize("detail", [False, True])
def test_read_errors_are_controlled_and_close_the_session(reports, detail, caplog):
    lost, _ = pair(reports)
    match = generated(reports, lost["id"])["items"][0]
    before = len(reports.sessions)

    def fail_match_read(conn, cursor, statement, parameters, context, executemany):
        if "from object_matches" in statement.casefold():
            raise SQLAlchemyError("internal-match-query-secret")

    event.listen(reports.engine, "before_cursor_execute", fail_match_read)
    try:
        path = match["id"] if detail else "me"
        response = reports.client.get(f"{MATCHES}/{path}", headers=reports.headers)
    finally:
        event.remove(reports.engine, "before_cursor_execute", fail_match_read)
    assert response.status_code == 503
    assert response.json() == {
        "detail": "El servicio de coincidencias no está disponible."
    }
    assert "internal-match-query-secret" not in response.text + caplog.text
    assert len(reports.sessions) == before + 1
    assert (
        reports.client.get(f"{MATCHES}/me", headers=reports.headers).status_code == 200
    )


@pytest.mark.parametrize("from_found", [False, True])
def test_earliest_valid_date_does_not_overflow_the_candidate_window(
    reports, from_found
):
    lost, found = (
        create_report(reports, "lost", event_date=date.min.isoformat()),
        create_report(reports, "found", mine=False, event_date=date.min.isoformat()),
    )
    assert (
        generated(reports, (found if from_found else lost)["id"], mine=not from_found)[
            "total"
        ]
        == 1
    )


def test_matches_are_sorted_by_creation_date_when_scores_are_equal(reports):
    lost, _ = pair(reports)
    create_report(reports, "found", mine=False)
    items = generated(reports, lost["id"])["items"]
    with Session(reports.connection) as session:
        session.get(ObjectMatch, UUID(items[0]["id"])).created_at -= timedelta(days=1)
        session.commit()
    page = reports.client.get(f"{MATCHES}/me", headers=reports.headers).json()
    assert page["items"][0]["id"] == items[1]["id"]
    assert page["items"][0]["percentage"] == page["items"][1]["percentage"]
