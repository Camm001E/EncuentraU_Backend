from unittest.mock import Mock

import pytest

from app.domain.image_analysis import ObjectImageAnalysis
from app.domain.visual_evidence_guard import review_badge_identification
from app.infrastructure.gemini_image_analyzer import GeminiImageAnalyzer
from tests.test_gemini_image_analyzer import FakeGeminiClient


def analysis(kind="chapa", features=None, confidence="alta"):
    return ObjectImageAnalysis(
        object_detected=True,
        object_type=kind,
        category="accesorios",
        primary_color="lila",
        brand=None,
        shape="circular",
        visible_features=features or ["dibujo de oso", "contorno circular"],
        image_quality="buena",
        confidence=confidence,
        requires_another_photo=False,
    )


@pytest.mark.parametrize("kind", ["chapa", "pin decorativo", "insignia", "pines"])
def test_decoration_without_fastener_requires_another_view(kind):
    original = analysis(kind)
    result, changed = review_badge_identification(original)
    assert changed and result.requires_another_photo
    assert result.object_type == "objeto decorativo de tipo no confirmado"
    assert result.confidence == "media" and "reverso" in result.warnings[-1]
    assert result.visible_features == original.visible_features
    assert original.object_type == kind and not original.requires_another_photo


@pytest.mark.parametrize(
    "feature",
    [
        "no se ve el alfiler",
        "sin aguja visible",
        "dibujo de alfiler",
        "posible enganche posterior",
        "alfiler oculto",
    ],
)
def test_missing_drawn_or_speculative_fastener_is_not_evidence(feature):
    result, changed = review_badge_identification(analysis(features=[feature]))
    assert changed and result.requires_another_photo


@pytest.mark.parametrize(
    "feature",
    [
        "alfiler metálico visible en el reverso",
        "imperdible posterior",
        "dos agujas de sujeción",
    ],
)
def test_visible_fastener_keeps_badge_identification(feature):
    original = analysis(features=[feature])
    result, changed = review_badge_identification(original)
    assert not changed and result == original


@pytest.mark.parametrize("kind", ["anillo", "billetera", "estuche", "chapa de puerta"])
def test_other_families_are_not_rewritten(kind):
    original = analysis(kind, ["piedra transparente rectangular"])
    result, changed = review_badge_identification(original)
    assert not changed and result == original


def test_review_never_increases_low_confidence():
    result, _ = review_badge_identification(analysis(confidence="baja"))
    assert result.confidence == "baja"


def test_gemini_applies_review_without_a_second_provider_call():
    client = FakeGeminiClient(analysis())
    client.models.generate_content = Mock(wraps=client.models.generate_content)
    analyzer = GeminiImageAnalyzer("test-key", "test-model", client=client)
    result = analyzer.analyze(b"image", "image/jpeg", "Un objeto")
    assert result.requires_another_photo
    assert result._metadata["type_adjusted"] is True
    assert result._metadata["evidence_review"] == "visible-fastener-v1"
    assert client.models.generate_content.call_count == 1
