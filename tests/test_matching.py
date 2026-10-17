from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.application.matching_service import MatchingService
from app.domain.matching import (
    MatchableObject,
    MatchEvaluation,
    MatchFactor,
    MatchFactorGroup,
    MatchFactorName,
    MatchFactorStatus,
    MatchLevel,
    MatchRequest,
)
from app.main import app

service = MatchingService()
client = TestClient(app)
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "matching"


def _request(case: str = "same_object") -> MatchRequest:
    return MatchRequest.model_validate_json((FIXTURE_DIR / f"{case}.json").read_bytes())


def _factor(result: MatchEvaluation, name: MatchFactorName) -> MatchFactor:
    return next(factor for factor in result.factors if factor.name == name)


def _identical_request() -> MatchRequest:
    obj = _request().lost
    return MatchRequest(lost=obj, found=obj)


@pytest.mark.parametrize(
    ("case", "level", "minimum", "maximum", "compatible"),
    [
        ("same_object", MatchLevel.HIGH, 85, 92, True),
        ("similar_object", MatchLevel.POSSIBLE, 60, 84, True),
        ("different_object", MatchLevel.LOW, 0, 29, False),
    ],
)
def test_saved_gemini_results(
    case: str, level: MatchLevel, minimum: int, maximum: int, compatible: bool
) -> None:
    result = service.evaluate(_request(case))

    assert result.level == level
    assert minimum <= result.percentage <= maximum
    assert result.compatible is compatible
    assert result.context_percentage == 100
    assert result.evidence_coverage == 92


def test_similar_object_is_at_least_five_points_below_same_object() -> None:
    same = service.evaluate(_request("same_object"))
    similar = service.evaluate(_request("similar_object"))

    assert same.percentage - similar.percentage >= 5


def test_unknown_brand_is_excluded_without_penalizing_matching_evidence() -> None:
    request = _identical_request()
    unknown = service.evaluate(request)
    known = service.evaluate(
        MatchRequest(
            lost=request.lost.model_copy(update={"brand": "Fabricante A"}),
            found=request.found.model_copy(update={"brand": "Fabricante A"}),
        )
    )

    brand = _factor(unknown, MatchFactorName.BRAND)
    assert brand.status == MatchFactorStatus.UNKNOWN
    assert brand.weight == 10
    assert brand.evaluable_weight == brand.score == 0
    assert unknown.identity_percentage == known.identity_percentage == 100
    assert unknown.percentage == known.percentage == 100
    assert unknown.evidence_coverage == 92
    assert known.evidence_coverage == 100


def test_known_brand_disagreement_remains_in_the_denominator() -> None:
    request = _identical_request()
    result = service.evaluate(
        MatchRequest(
            lost=request.lost.model_copy(update={"brand": "Fabricante A"}),
            found=request.found.model_copy(update={"brand": "Fabricante B"}),
        )
    )

    brand = _factor(result, MatchFactorName.BRAND)
    assert brand.status == MatchFactorStatus.DIFFERENT
    assert brand.score == 0
    assert brand.evaluable_weight == 10
    assert result.identity_percentage == 90
    assert result.evidence_coverage == 100
    assert any("Marca" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("primary", "left_secondary", "right_secondary"),
    [("negro", "azul", "rojo"), ("gris", "verde", "amarillo")],
)
def test_different_secondary_colors_do_not_receive_full_color_points(
    primary: str, left_secondary: str, right_secondary: str
) -> None:
    obj = _request().lost
    result = service.evaluate(
        MatchRequest(
            lost=obj.model_copy(
                update={"primary_color": primary, "secondary_colors": [left_secondary]}
            ),
            found=obj.model_copy(
                update={"primary_color": primary, "secondary_colors": [right_secondary]}
            ),
        )
    )

    color = _factor(result, MatchFactorName.COLOR)
    assert color.status == MatchFactorStatus.PARTIAL
    assert color.score == color.weight * 0.6
    assert color.evaluable_weight == color.weight
    assert any("colores secundarios" in warning for warning in result.warnings)


@pytest.mark.parametrize("secondaries", [[], ["azul"]])
def test_unavailable_secondary_colors_only_evaluate_primary_component(
    secondaries: list[str],
) -> None:
    obj = _request().lost
    result = service.evaluate(
        MatchRequest(
            lost=obj.model_copy(update={"secondary_colors": secondaries}),
            found=obj.model_copy(update={"secondary_colors": []}),
        )
    )

    color = _factor(result, MatchFactorName.COLOR)
    assert color.status == MatchFactorStatus.MATCH
    assert color.evaluable_weight == color.score == 9
    assert result.identity_percentage == result.percentage == 100
    assert result.evidence_coverage == 87.2


def test_secondary_colors_can_be_evaluated_without_primary_colors() -> None:
    obj = _request().lost.model_copy(update={"primary_color": None})
    result = service.evaluate(MatchRequest(lost=obj, found=obj))

    color = _factor(result, MatchFactorName.COLOR)
    assert color.evaluable_weight == color.score == 6
    assert color.status == MatchFactorStatus.MATCH
    assert result.identity_percentage == 100
    assert result.evidence_coverage == 84.8


def test_shape_and_visual_features_are_independent() -> None:
    obj = MatchableObject(
        object_type="recipiente", shape="ovalado", visible_features=["tapa metálica"]
    )
    result = service.evaluate(
        MatchRequest(lost=obj, found=obj.model_copy(update={"shape": "rectangular"}))
    )

    assert _factor(result, MatchFactorName.SHAPE).status == MatchFactorStatus.DIFFERENT
    visual = _factor(result, MatchFactorName.VISUAL_FEATURES)
    assert visual.status == MatchFactorStatus.MATCH
    assert visual.score == 20


def test_visual_features_preserve_boundaries_instead_of_pooling_words() -> None:
    obj = MatchableObject(
        object_type="accesorio", visible_features=["banda verde", "pieza metálica"]
    )
    found = obj.model_copy(
        update={"visible_features": ["banda metálica", "pieza verde"]}
    )

    result = service.evaluate(MatchRequest(lost=obj, found=found))

    visual = _factor(result, MatchFactorName.VISUAL_FEATURES)
    assert visual.status == MatchFactorStatus.PARTIAL
    assert 0 < visual.score < visual.weight


def test_duplicate_features_and_order_do_not_inflate_similarity() -> None:
    request = _request()
    original = service.evaluate(request)
    changed = service.evaluate(
        MatchRequest(
            lost=request.lost.model_copy(
                update={"visible_features": request.lost.visible_features * 2}
            ),
            found=request.found.model_copy(
                update={
                    "visible_features": list(reversed(request.found.visible_features))
                }
            ),
        )
    )
    reversed_result = service.evaluate(
        MatchRequest(lost=request.found, found=request.lost)
    )

    name = MatchFactorName.VISUAL_FEATURES
    assert _factor(original, name).score == _factor(changed, name).score
    assert _factor(original, name).score == _factor(reversed_result, name).score


@pytest.mark.parametrize(
    "verb", ["perdí", "perdido", "encontré", "encontrado", "hallado", "extraviado"]
)
def test_description_ignores_report_words_and_location(verb: str) -> None:
    obj = _request().lost
    result = service.evaluate(
        MatchRequest(
            lost=obj.model_copy(
                update={
                    "description": "Audífonos negros",
                    "location": "Cafetería central",
                }
            ),
            found=obj.model_copy(
                update={
                    "description": (
                        f"{verb} unos audífonos negros en la cafetería central"
                    ),
                    "location": "Cafetería central",
                }
            ),
        )
    )

    assert (
        _factor(result, MatchFactorName.DESCRIPTION).status == MatchFactorStatus.MATCH
    )


def test_shared_location_does_not_match_unrelated_descriptions() -> None:
    request = _request()
    result = service.evaluate(
        MatchRequest(
            lost=request.lost.model_copy(
                update={"description": "Perdí una taza negra en la cafetería central"}
            ),
            found=request.found.model_copy(
                update={
                    "description": "Encontré un reloj blanco en la cafetería central"
                }
            ),
        )
    )

    description = _factor(result, MatchFactorName.DESCRIPTION)
    assert description.status == MatchFactorStatus.DIFFERENT
    assert description.score == 0


def test_description_with_only_report_and_location_words_is_unknown() -> None:
    obj = _request().lost.model_copy(
        update={"description": "Perdido en la cafetería central"}
    )

    result = service.evaluate(MatchRequest(lost=obj, found=obj))

    description = _factor(result, MatchFactorName.DESCRIPTION)
    assert description.status == MatchFactorStatus.UNKNOWN
    assert description.evaluable_weight == 0


def test_normalization_handles_accents_synonyms_and_requested_word_forms() -> None:
    left = MatchableObject(
        object_type="auriculares inalámbricos",
        primary_color="negros",
        secondary_colors=["azules"],
        visible_features=["almohadillas acolchadas", "detalles azules en las copas"],
        description="Audífonos inalámbricos negros",
    )
    right = MatchableObject(
        object_type=" AUDÍFONO Bluetooth ",
        primary_color="negro",
        secondary_colors=["azul"],
        visible_features=["almohadilla acolchado", "detalle azul en la copa"],
        description="Auricular inalámbrica negra",
    )

    result = service.evaluate(MatchRequest(lost=left, found=right))

    for name in (
        MatchFactorName.OBJECT_TYPE,
        MatchFactorName.COLOR,
        MatchFactorName.VISUAL_FEATURES,
        MatchFactorName.DESCRIPTION,
    ):
        assert _factor(result, name).status == MatchFactorStatus.MATCH


def test_matching_location_and_date_cannot_override_incompatible_types() -> None:
    result = service.evaluate(_request("different_object"))

    assert result.context_percentage == 100
    assert result.compatible is False
    assert result.percentage <= 29
    assert result.level == MatchLevel.LOW
    assert any("incompatibles" in warning for warning in result.warnings)


@pytest.mark.parametrize(("shared_words", "compatible"), [(6, False), (7, True)])
def test_object_type_compatibility_boundary(
    shared_words: int, compatible: bool
) -> None:
    left = MatchableObject(
        object_type=" ".join(f"pieza{i}" for i in range(shared_words))
    )
    right = MatchableObject(object_type=" ".join(f"pieza{i}" for i in range(20)))

    result = service.evaluate(MatchRequest(lost=left, found=right))

    assert result.compatible is compatible
    if not compatible:
        assert result.percentage <= 29


def test_all_unknown_evidence_returns_zero_without_dividing_by_zero() -> None:
    obj = MatchableObject(
        object_type=" ",
        category="Desconocida",
        primary_color="No visible",
        brand="Sin marca",
        shape="No se distingue",
        visible_features=["N/A"],
        visible_text=[""],
        location="No identificado",
        description=" ",
    )

    result = service.evaluate(MatchRequest(lost=obj, found=obj))

    assert (
        result.percentage
        == result.identity_percentage
        == result.context_percentage
        == 0
    )
    assert result.evidence_coverage == 0
    assert result.level == MatchLevel.LOW
    assert all(f.status == MatchFactorStatus.UNKNOWN for f in result.factors)
    assert all(f.evaluable_weight == f.score == 0 for f in result.factors)
    assert result.warnings


def test_unavailable_context_does_not_receive_the_identity_weight() -> None:
    obj = _request().lost.model_copy(update={"location": None, "event_date": None})

    result = service.evaluate(MatchRequest(lost=obj, found=obj))

    assert result.identity_percentage == 100
    assert result.context_percentage == 0
    assert result.percentage == 80
    assert result.evidence_coverage == 72


def test_reversed_dates_affect_context_and_produce_a_warning() -> None:
    request = _identical_request()
    result = service.evaluate(
        MatchRequest(
            lost=request.lost,
            found=request.found.model_copy(update={"event_date": date(2026, 10, 15)}),
        )
    )

    assert result.identity_percentage == 100
    assert result.context_percentage == 60
    assert _factor(result, MatchFactorName.DATE).score == 0
    assert any("anterior" in warning for warning in result.warnings)


def test_matching_endpoint_returns_new_fields_and_grouped_evidence() -> None:
    response = client.post(
        "/api/v1/matches/evaluate", json=_identical_request().model_dump(mode="json")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["percentage"] == 100
    assert body["identity_percentage"] == 100
    assert body["context_percentage"] == 100
    assert body["evidence_coverage"] == 92
    assert body["compatible"] is True
    assert body["level"] == "high"
    assert len(body["factors"]) == 9
    assert {f["name"] for f in body["factors"]} == set(MatchFactorName)
    for group in MatchFactorGroup:
        assert sum(f["weight"] for f in body["factors"] if f["group"] == group) == 100
    assert all(
        0 <= f["score"] <= f["evaluable_weight"] <= f["weight"] for f in body["factors"]
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"lost": {}},
        {"lost": {}, "found": {}, "unexpected": True},
        {"lost": {}, "found": {"event_date": "2026-02-30"}},
        {"lost": {}, "found": {"invented_attribute": "value"}},
    ],
)
def test_matching_endpoint_rejects_invalid_contracts(payload: dict) -> None:
    response = client.post("/api/v1/matches/evaluate", json=payload)

    assert response.status_code == 422
