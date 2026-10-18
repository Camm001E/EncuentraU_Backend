from io import BytesIO
from uuid import UUID, uuid4

import pytest
from alembic import command
from PIL import Image
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.infrastructure.auth_security import JWTAccessTokenService
from app.infrastructure.database.models import ReportImage, User
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository
from tests.test_matches_postgresql import generated, pair
from tests.test_migrations import migration_config
from tests.test_report_images import photo
from tests.test_reports_postgresql import (
    create,
)
from tests.test_reports_postgresql import (
    reports as reports,
)
from tests.test_reports_postgresql import (
    reports_engine as reports_engine,
)

pytestmark = pytest.mark.postgresql


@pytest.fixture
def images(reports, tmp_path):
    reports.settings.report_image_storage_path = tmp_path
    return reports, tmp_path


def url(report_id):
    return f"/api/v1/reports/{report_id}/image"


def upload(
    ctx,
    report_id,
    *,
    headers=None,
    fmt="PNG",
    color="blue",
    filename=None,
    mime=None,
    data=None,
):
    ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[fmt]
    content_type = (
        mime or {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]
    )
    return ctx.client.put(
        url(report_id),
        headers=headers or ctx.headers,
        files={
            "image": (
                filename or "photo." + ext,
                photo(fmt, color) if data is None else data,
                content_type,
            )
        },
    )


def third_headers(ctx, role="student"):
    with Session(ctx.connection) as session:
        user = User(
            full_name="Third",
            email=f"{uuid4().hex}@example.com",
            student_code=uuid4().hex,
            password_hash="unused",
            role=role,
        )
        session.add(user)
        session.flush()
        user_id = user.id
        session.commit()
        token = (
            JWTAccessTokenService(ctx.settings)
            .issue(SQLAlchemyUserRepository(session).get_by_id(user_id))
            .value
        )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_upload_metadata_content_persist_and_owner_report_includes_safe_reference(
    images, fmt
):
    ctx, root = images
    report = create(ctx)
    assert report["image"] is None
    result = upload(ctx, report["id"], fmt=fmt)
    assert result.status_code == 200
    metadata = result.json()
    assert metadata["report_id"] == report["id"] and metadata["width"] == 20
    assert not {"storage_key", "original_filename", "path", "user_id"}.intersection(
        metadata
    )
    assert ctx.client.get(url(report["id"]), headers=ctx.headers).json() == metadata
    content = ctx.client.get(url(report["id"]) + "/content", headers=ctx.headers)
    assert (
        content.status_code == 200
        and content.headers["content-type"] == metadata["content_type"]
    )
    assert content.headers["cache-control"] == "private, no-store"
    with Image.open(BytesIO(content.content)) as decoded:
        assert decoded.format == fmt
    persisted = ctx.client.get(
        f"/api/v1/reports/{report['id']}", headers=ctx.headers
    ).json()
    assert persisted["image"] == metadata
    with Session(ctx.connection) as session:
        row = session.scalar(select(ReportImage))
        assert row.original_filename.startswith("photo.")
        assert (root / row.storage_key).is_file()
        assert str(root) not in str(metadata)


def test_replacement_deletes_old_file_and_delete_removes_row_and_file(images):
    ctx, root = images
    report_id = create(ctx)["id"]
    first = upload(ctx, report_id).json()
    old = next(root.iterdir())
    second = upload(ctx, report_id, color="red").json()
    assert first["id"] == second["id"] and first["sha256"] != second["sha256"]
    assert not old.exists() and len(list(root.iterdir())) == 1
    assert second["updated_at"] >= second["created_at"]
    assert ctx.client.delete(url(report_id), headers=ctx.headers).status_code == 204
    assert list(root.iterdir()) == []
    assert ctx.client.get(url(report_id), headers=ctx.headers).status_code == 404
    assert (
        ctx.client.get(url(report_id) + "/content", headers=ctx.headers).status_code
        == 404
    )
    with Session(ctx.connection) as session:
        assert session.scalar(select(func.count()).select_from(ReportImage)) == 0


def test_match_participant_can_read_both_photographs_but_not_mutate_other(images):
    ctx, _ = images
    lost, found = pair(ctx)
    left = upload(ctx, lost["id"]).json()
    right = upload(ctx, found["id"], headers=ctx.other_headers, color="red").json()
    assert ctx.client.get(url(found["id"]), headers=ctx.headers).status_code == 404
    match = generated(ctx, lost["id"])["items"][0]
    assert (
        match["my_report"]["image"] == left
        and match["candidate_report"]["image"] == right
    )
    for headers in [ctx.headers, ctx.other_headers]:
        for report in [lost, found]:
            assert ctx.client.get(url(report["id"]), headers=headers).status_code == 200
            assert (
                ctx.client.get(
                    url(report["id"]) + "/content", headers=headers
                ).status_code
                == 200
            )
    for method in ["put", "delete"]:
        response = (
            upload(ctx, found["id"])
            if method == "put"
            else ctx.client.delete(url(found["id"]), headers=ctx.headers)
        )
        assert response.status_code == 404
    outsider = third_headers(ctx)
    for suffix in ["", "/content"]:
        assert (
            ctx.client.get(url(lost["id"]) + suffix, headers=outsider).status_code
            == 404
        )
    assert (
        ctx.client.get(url(lost["id"]), headers=third_headers(ctx, "admin")).status_code
        == 200
    )
    serialized = str(match)
    for forbidden in [
        "private_feature",
        "user_id",
        "student_code",
        "email",
        "storage_key",
        "original_filename",
        "extracted_data",
    ]:
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "invalid", ["mime", "extension", "corrupt", "empty", "too_large", "traversal"]
)
def test_invalid_uploads_are_controlled_and_leave_previous_file_unchanged(
    images, invalid
):
    ctx, root = images
    report_id = create(ctx)["id"]
    before = upload(ctx, report_id).json()
    changes, status = {
        "mime": ({"mime": "image/jpeg"}, 415),
        "extension": ({"filename": "image.exe"}, 415),
        "corrupt": ({"data": b"not a photograph"}, 422),
        "empty": ({"data": b""}, 422),
        "too_large": ({"data": b"x" * 8_388_609}, 413),
        "traversal": ({"filename": "../../image.png"}, 422),
    }[invalid]
    response = upload(ctx, report_id, **changes)
    assert response.status_code == status
    assert str(root) not in response.text and "Traceback" not in response.text
    assert ctx.client.get(url(report_id), headers=ctx.headers).json() == before
    assert len(list(root.iterdir())) == 1


def test_missing_jwt_unrelated_and_missing_reports_do_not_expose_existence(images):
    ctx, _ = images
    report_id = create(ctx)["id"]
    upload(ctx, report_id)
    for suffix in ["", "/content"]:
        assert ctx.client.get(url(report_id) + suffix).status_code == 401
        assert (
            ctx.client.get(
                url(report_id) + suffix, headers={"Authorization": "Bearer invalid"}
            ).status_code
            == 401
        )
        assert (
            ctx.client.get(url(uuid4()) + suffix, headers=ctx.headers).status_code
            == 404
        )
    assert (
        ctx.client.put(
            url(report_id), files={"image": ("photo.png", photo(), "image/png")}
        ).status_code
        == 401
    )
    assert ctx.client.delete(url(report_id)).status_code == 401


def test_old_reports_and_matches_without_image_remain_compatible(images):
    ctx, _ = images
    lost, _ = pair(ctx)
    assert (
        ctx.client.get(f"/api/v1/reports/{lost['id']}", headers=ctx.headers).json()[
            "image"
        ]
        is None
    )
    match = generated(ctx, lost["id"])["items"][0]
    assert (
        match["my_report"]["image"] is None
        and match["candidate_report"]["image"] is None
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("report_id", "duplicate"),
        ("storage_key", "duplicate"),
        ("size_bytes", 0),
        ("width", 0),
        ("height", 4097),
        ("content_type", "text/html"),
        ("sha256", "bad"),
    ],
)
def test_postgresql_image_constraints(images, field, value):
    ctx, _ = images
    report_id = create(ctx)["id"]
    upload(ctx, report_id)
    other_id = create(ctx)["id"]
    with Session(ctx.connection) as session:
        existing = session.scalar(select(ReportImage))
        values = dict(
            report_id=UUID(other_id),
            storage_key=uuid4().hex + ".png",
            original_filename="photo.png",
            content_type="image/png",
            size_bytes=1,
            sha256="0" * 64,
            width=1,
            height=1,
        )
        values[field] = getattr(existing, field) if value == "duplicate" else value
        session.add(ReportImage(**values))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_alembic_sees_no_schema_differences_after_image_migration(images):
    ctx, _ = images
    config = migration_config()
    config.attributes["connection"] = ctx.connection
    command.check(config)


def test_failed_image_transaction_preserves_previous_database_row_and_file(images):
    ctx, root = images
    report_id = create(ctx)["id"]
    before = upload(ctx, report_id).json()
    old_file = next(root.iterdir())

    def reject_write(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("UPDATE REPORT_IMAGES"):
            raise SQLAlchemyError("simulated write failure")

    event.listen(ctx.connection, "before_cursor_execute", reject_write)
    try:
        response = upload(ctx, report_id, color="red")
        assert response.status_code == 503
    finally:
        event.remove(ctx.connection, "before_cursor_execute", reject_write)
    assert ctx.client.get(url(report_id), headers=ctx.headers).json() == before
    assert old_file.is_file() and len(list(root.iterdir())) == 1


def test_storage_corruption_is_not_served_to_another_student(images):
    ctx, root = images
    report_id = create(ctx)["id"]
    upload(ctx, report_id)
    next(root.iterdir()).write_bytes(b"corrupt")
    response = ctx.client.get(url(report_id) + "/content", headers=ctx.headers)
    assert response.status_code == 503
    assert str(root) not in response.text
