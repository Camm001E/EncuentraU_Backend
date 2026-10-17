from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import LargeBinary, create_engine, event, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.infrastructure.database import session as database_session
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import (
    ImageAnalysis,
    ObjectMatch,
    ObjectReport,
    User,
)


@pytest.fixture
def engine():
    db_engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(db_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(db_engine)
    yield db_engine
    db_engine.dispose()


def make_user(**changes) -> User:
    values = {
        "full_name": "Usuario de prueba",
        "email": f"{uuid4().hex}@example.test",
        "student_code": uuid4().hex,
        "password_hash": "example-test-hash",
    }
    return User(**{**values, **changes})


def make_report(user_id, report_type="lost", **changes) -> ObjectReport:
    values = {
        "user_id": user_id,
        "report_type": report_type,
        "object_type": "objeto de prueba",
        "category": "accesorios",
        "description": "Descripción de prueba",
        "location": "Laboratorio",
        "event_date": date(2026, 10, 16),
    }
    return ObjectReport(**{**values, **changes})


def make_match(lost_id, found_id, **changes) -> ObjectMatch:
    values = {
        "lost_report_id": lost_id,
        "found_report_id": found_id,
        "percentage": 84,
        "identity_percentage": Decimal("80.00"),
        "context_percentage": Decimal("100.00"),
        "evidence_coverage": Decimal("92.00"),
        "compatible": True,
        "level": "possible",
    }
    return ObjectMatch(**{**values, **changes})


@pytest.fixture
def reports(engine):
    with Session(engine) as session:
        user = make_user()
        session.add(user)
        session.flush()
        lost = make_report(user.id)
        found = make_report(user.id, "found")
        session.add_all([lost, found])
        session.flush()
        ids = (user.id, lost.id, found.id)
        session.commit()
        return ids


def test_metadata_contains_all_tables_and_no_binary_image_columns(engine) -> None:
    assert set(inspect(engine).get_table_names()) == {
        "users",
        "object_reports",
        "image_analyses",
        "object_matches",
    }
    for table in Base.metadata.tables.values():
        assert "id" in table.c
        assert "created_at" in table.c
        assert not any(isinstance(column.type, LargeBinary) for column in table.c)
    assert "updated_at" in User.__table__.c
    assert "updated_at" in ObjectReport.__table__.c


def test_metadata_compiles_native_postgresql_uuid_jsonb_and_timestamps() -> None:
    ddl = "\n".join(
        str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for table in Base.metadata.sorted_tables
    )
    assert "UUID" in ddl
    assert "JSONB" in ddl
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "uq_object_matches_pair" in ddl


@pytest.mark.parametrize("field", ["email", "student_code"])
def test_user_identity_fields_are_unique(engine, field: str) -> None:
    with Session(engine) as session:
        first = make_user()
        session.add(first)
        session.flush()
        session.add(make_user(**{field: getattr(first, field)}))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_defaults_uuid_and_timestamps_are_assigned(engine) -> None:
    with Session(engine) as session:
        user = make_user()
        session.add(user)
        session.flush()
        assert user.id.version == 4
        assert user.role == "student"
        assert user.is_active is True
        assert user.created_at is not None
        assert user.updated_at is not None


def test_matches_have_unique_pairs_and_cannot_match_themselves(engine, reports) -> None:
    _, lost, found = reports
    with Session(engine) as session:
        session.add(make_match(lost, found))
        session.commit()
        session.add(make_match(lost, found))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        session.add(make_match(lost, lost))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize(
    "changes",
    [
        {"percentage": -1},
        {"percentage": 101},
        {"identity_percentage": 101},
        {"context_percentage": -1},
        {"evidence_coverage": 101},
        {"level": "invalid"},
        {"status": "invalid"},
        {"compatible": False, "percentage": 84},
        {"compatible": False, "percentage": 29, "level": "high"},
    ],
)
def test_match_metrics_and_states_are_constrained(
    engine, reports, changes: dict
) -> None:
    _, lost, found = reports
    with Session(engine) as session:
        session.add(make_match(lost, found, **changes))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize(
    ("kind", "changes"),
    [
        ("user", {"role": "invalid"}),
        ("report", {"report_type": "invalid"}),
        ("report", {"status": "invalid"}),
        ("analysis", {"confidence": "invalid"}),
    ],
)
def test_user_report_and_analysis_states_are_constrained(
    engine, reports, kind: str, changes: dict
) -> None:
    user_id, lost, _ = reports
    if kind == "user":
        obj = make_user(**changes)
    elif kind == "report":
        obj = make_report(user_id, **changes)
    else:
        obj = ImageAnalysis(
            report_id=lost,
            provider="example",
            model="example",
            extracted_data={},
            **changes,
        )
    with Session(engine) as session:
        session.add(obj)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize("kind", ["report", "analysis", "match"])
def test_foreign_keys_reject_orphans(engine, reports, kind: str) -> None:
    _, lost, found = reports
    if kind == "report":
        obj = make_report(uuid4())
    elif kind == "analysis":
        obj = ImageAnalysis(
            report_id=uuid4(),
            provider="example",
            model="example",
            extracted_data={},
            confidence="alta",
        )
    else:
        obj = make_match(uuid4(), found)
    with Session(engine) as session:
        session.add(obj)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_report_deletion_cascades_analysis_and_matches(engine, reports) -> None:
    _, lost, found = reports
    with Session(engine) as session:
        session.add_all(
            [
                make_match(lost, found),
                ImageAnalysis(
                    report_id=found,
                    provider="example",
                    model="example",
                    extracted_data={"object_detected": True},
                    confidence="alta",
                ),
            ]
        )
        session.commit()
        session.delete(session.get(ObjectReport, found))
        session.commit()
        assert session.scalar(select(func.count()).select_from(ImageAnalysis)) == 0
        assert session.scalar(select(func.count()).select_from(ObjectMatch)) == 0


def test_users_with_reports_cannot_be_deleted(engine, reports) -> None:
    user_id, _, _ = reports
    with Session(engine) as session:
        session.delete(session.get(User, user_id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize("raises", [False, True])
def test_session_dependency_closes_and_rolls_back_uncommitted_work(
    engine, monkeypatch, raises: bool
) -> None:
    factory = database_session.create_session_factory(engine)
    monkeypatch.setattr(database_session, "get_session_factory", lambda: factory)
    dependency = database_session.get_session()
    session = next(dependency)
    session.add(make_user())
    session.flush()
    assert session.in_transaction()
    if raises:
        with pytest.raises(RuntimeError, match="example failure"):
            dependency.throw(RuntimeError("example failure"))
    else:
        with pytest.raises(StopIteration):
            next(dependency)
    assert not session.in_transaction()
    with Session(engine) as check:
        assert check.scalar(select(func.count()).select_from(User)) == 0
