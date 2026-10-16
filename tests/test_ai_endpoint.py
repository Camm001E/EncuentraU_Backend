from fastapi.testclient import TestClient

from app.domain.image_analysis import ObjectImageAnalysis
from app.infrastructure.gemini_image_analyzer import get_image_analyzer
from app.main import app


class FakeImageAnalyzer:
    def analyze(
        self,
        image_bytes: bytes,
        mime_type: str,
        description: str,
    ) -> ObjectImageAnalysis:
        assert image_bytes == b"fake-image-content"
        assert mime_type == "image/jpeg"
        assert description == "Audífonos negros encontrados en la cafetería"
        return ObjectImageAnalysis(
            object_detected=True,
            object_type="audifonos inalambricos",
            category="electronica",
            primary_color="negro",
            secondary_colors=[],
            brand=None,
            shape="intraurales con estuche rectangular",
            visible_features=["estuche negro"],
            visible_text=[],
            image_quality="buena",
            confidence="alta",
            requires_another_photo=False,
            warnings=[],
        )


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["phase"] == "phase-1"


def test_analyze_image_returns_structured_result() -> None:
    app.dependency_overrides[get_image_analyzer] = lambda: FakeImageAnalyzer()
    try:
        response = client.post(
            "/api/v1/ai/analyze",
            data={"description": "Audífonos negros encontrados en la cafetería"},
            files={
                "image": (
                    "audifonos.jpg",
                    b"fake-image-content",
                    "image/jpeg",
                )
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["object_type"] == "audifonos inalambricos"
    assert body["primary_color"] == "negro"
    assert body["brand"] is None
    assert body["requires_another_photo"] is False


def test_analyze_image_rejects_unsupported_file_type() -> None:
    app.dependency_overrides[get_image_analyzer] = lambda: FakeImageAnalyzer()
    try:
        response = client.post(
            "/api/v1/ai/analyze",
            data={"description": "Archivo que no corresponde a una fotografía"},
            files={"image": ("objeto.txt", b"not-an-image", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 415
    assert "JPEG, PNG o WEBP" in response.json()["detail"]


def test_analyze_image_rejects_empty_file() -> None:
    app.dependency_overrides[get_image_analyzer] = lambda: FakeImageAnalyzer()
    try:
        response = client.post(
            "/api/v1/ai/analyze",
            data={"description": "Fotografía vacía para validar el endpoint"},
            files={"image": ("objeto.jpg", b"", "image/jpeg")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "La fotografía está vacía."
