import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from app.application.report_images import ReportImageService
from app.core.config import Settings
from app.domain.report_images import (
    ImageAccess,
    ImageDimensionsError,
    ImageReference,
    ImageTooLargeError,
    ImageTypeError,
    ImageUnavailableError,
    ImageValidationError,
    ReportImage,
)
from app.domain.users import User
from app.infrastructure.image_processor import PillowImageProcessor
from app.infrastructure.local_image_storage import LocalImageStorage


def photo(fmt="PNG", color="blue", size=(20, 12), *, exif=False):
    output = BytesIO()
    options = {}
    if exif:
        tags = Image.Exif()
        tags[274] = 6
        tags[270] = "private image metadata"
        options["exif"] = tags
    Image.new("RGB", size, color).save(output, format=fmt, **options)
    return output.getvalue()


@pytest.mark.parametrize(
    "fmt,mime,extension",
    [
        ("JPEG", "image/jpeg", "jpg"),
        ("PNG", "image/png", "png"),
        ("WEBP", "image/webp", "webp"),
    ],
)
def test_real_decoding_normalizes_each_supported_format(fmt, mime, extension):
    result = PillowImageProcessor(8_388_608).process(
        photo(fmt), f"photo.{extension}", mime
    )
    assert result.content_type == mime and result.extension == extension
    assert result.sha256 == hashlib.sha256(result.data).hexdigest()
    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.format == fmt and decoded.size == (20, 12)
        assert not decoded.getexif()


def test_exif_orientation_is_applied_and_all_metadata_removed():
    result = PillowImageProcessor(8_388_608).process(
        photo("JPEG", exif=True), "camera.jpg", "image/jpeg"
    )
    assert (result.width, result.height) == (12, 20)
    with Image.open(BytesIO(result.data)) as decoded:
        assert not decoded.getexif() and "exif" not in decoded.info
    assert b"private image metadata" not in result.data


@pytest.mark.parametrize(
    "name,mime",
    [
        ("camera.png", "image/jpeg"),
        ("camera.jpg", "image/png"),
        ("camera.exe", "image/png"),
        ("camera.png", "text/html"),
    ],
)
def test_mime_extension_and_actual_content_must_agree(name, mime):
    with pytest.raises(ImageTypeError):
        PillowImageProcessor(8_388_608).process(photo(), name, mime)


@pytest.mark.parametrize(
    "data",
    [b"", b"<html>not a photo</html>", b"\x89PNG\r\n\x1a\n", b"\xff\xd8truncated"],
)
def test_empty_corrupt_or_disguised_images_rejected(data):
    with pytest.raises(ImageValidationError):
        PillowImageProcessor(8_388_608).process(data, "photo.png", "image/png")


@pytest.mark.parametrize(
    "name",
    [
        "../photo.png",
        "..\\photo.png",
        "/photo.png",
        "C:\\photo.png",
        "nul\x00.png",
        "x" * 260 + ".png",
    ],
)
def test_untrusted_client_filename_cannot_traverse_storage(name):
    with pytest.raises(ImageValidationError):
        PillowImageProcessor(8_388_608).process(photo(), name, "image/png")


def test_byte_and_dimension_limits_and_resize():
    with pytest.raises(ImageTooLargeError):
        PillowImageProcessor(10).process(photo(), "photo.png", "image/png")
    with pytest.raises(ImageDimensionsError):
        PillowImageProcessor(8_388_608).process(
            photo(size=(16385, 1)), "photo.png", "image/png"
        )
    result = PillowImageProcessor(8_388_608).process(
        photo(size=(5000, 2)), "photo.png", "image/png"
    )
    assert max(result.width, result.height) == 4096


def test_local_storage_is_atomic_and_safe(tmp_path):
    storage = LocalImageStorage(tmp_path)
    key = uuid4().hex + ".png"
    storage.write(key, b"bytes")
    assert storage.read(key) == b"bytes"
    with pytest.raises(ImageUnavailableError):
        storage.write(key, b"overwrite")
    assert storage.read(key) == b"bytes"
    storage.delete(key)
    storage.delete(key)
    with patch(
        "app.infrastructure.local_image_storage.os.replace", side_effect=OSError
    ):
        with pytest.raises(ImageUnavailableError):
            storage.write(key, b"bytes")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "key",
    [
        "../escape.png",
        "..\\escape.png",
        "/etc/passwd",
        "C:\\secret",
        "x.png",
        "a" * 32 + ".exe",
    ],
)
def test_storage_rejects_opaque_key_traversal_for_every_operation(tmp_path, key):
    storage = LocalImageStorage(tmp_path)
    for operation in [
        lambda: storage.write(key, b"x"),
        lambda: storage.read(key),
        lambda: storage.delete(key),
    ]:
        with pytest.raises(ImageUnavailableError):
            operation()


def test_failed_database_commit_compensates_new_file_and_preserves_previous(tmp_path):
    storage = LocalImageStorage(tmp_path)
    owner = User(uuid4(), "Owner", "owner@example.com", "OWNER", "unused")
    report_id = uuid4()
    now = datetime.now(UTC)
    ref = ImageReference(uuid4(), report_id, "image/png", 1, "0" * 64, 20, 12, now, now)
    old = ReportImage(ref, uuid4().hex + ".png", "old.png")
    storage.write(old.storage_key, b"old")

    @contextmanager
    def failed_commit(*_args, **_kwargs):
        yield ImageAccess(owner.id, "active", False, old)
        raise ImageUnavailableError

    repository = Mock(transaction=failed_commit)
    service = ReportImageService(repository, storage, PillowImageProcessor(8_388_608))
    with pytest.raises(ImageUnavailableError):
        service.upload(report_id, owner, photo(), "new.png", "image/png")
    assert [p.name for p in tmp_path.iterdir()] == [old.storage_key]
    assert storage.read(old.storage_key) == b"old"


def test_image_configuration_defaults_and_invalid_limits():
    settings = Settings(_env_file=None)
    assert settings.report_image_storage_provider == "local"
    assert str(settings.report_image_storage_path).replace("\\", "/") == "var/uploads"
    assert settings.report_image_max_bytes == 8_388_608
    with pytest.raises(ValidationError):
        Settings(_env_file=None, report_image_max_bytes=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, report_image_storage_provider="public-static")
