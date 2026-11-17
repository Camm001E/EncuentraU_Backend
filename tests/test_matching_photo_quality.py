from datetime import date

import pytest

from app.application.matching_service import MatchingService
from app.application.object_matches import to_matchable_object
from app.domain.matching import MatchableObject, MatchRequest
from tests.test_match_orchestration import report


@pytest.mark.parametrize(
    "quality",
    [
        {"requires_another_photo": True},
        {"image_quality": "mala"},
    ],
)
@pytest.mark.parametrize("side", ["lost", "found"])
def test_insufficient_photo_cannot_be_high_even_with_identical_features(quality, side):
    obj = MatchableObject(
        object_type="mochila",
        primary_color="azul",
        visible_features=["parche triangular rojo"],
        location="Campus",
        event_date=date(2026, 1, 1),
    )
    pair = {"lost": obj, "found": obj}
    assert MatchingService().evaluate(MatchRequest(**pair)).level == "high"
    pair[side] = obj.model_copy(update=quality)
    result = MatchingService().evaluate(MatchRequest(**pair))
    assert result.level == "possible"
    assert result.percentage < 85
    assert any("otra fotografia" in w for w in result.warnings)


def test_quality_flags_survive_report_adaptation():
    obj = to_matchable_object(
        report(extracted={"requires_another_photo": True, "image_quality": "mala"})
    )
    assert obj.requires_another_photo is True
    assert obj.image_quality == "mala"


@pytest.mark.parametrize("bad", ["false", [], {}, 1, None])
def test_malformed_legacy_quality_is_not_coerced(bad):
    obj = to_matchable_object(
        report(extracted={"requires_another_photo": bad, "image_quality": bad})
    )
    assert obj.requires_another_photo is False
    assert obj.image_quality is None
