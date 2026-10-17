from datetime import date

from fastapi.testclient import TestClient

from app.application.matching_service import MatchingService
from app.domain.matching import (
    MatchableObject,
    MatchFactorName,
    MatchFactorStatus,
    MatchLevel,
    MatchRequest,
)
from app.main import app

service = MatchingService()
client = TestClient(app)


def _lost_headphones() -> MatchableObject:
    return MatchableObject(
        object_type="audífonos Bluetooth",
        category="electronica",
        primary_color="negro",
        secondary_colors=[],
        brand="JBL",
        shape="estuche ovalado",
        visible_features=[
            "audífonos intraurales",
            "estuche compacto",
            "puerto USB-C",
        ],
        visible_text=["JBL"],
        location="Cafetería central",
        event_date=date(2026, 9, 1),
        description="Audífonos Bluetooth negros en estuche ovalado compacto.",
    )


def test_same_object_is_high_after_normalizing_text() -> None:
    lost = _lost_headphones()
    found = MatchableObject(
        **{
            **lost.model_dump(),
            "object_type": " AURICULARES INALÁMBRICOS ",
            "category": "Electrónica",
            "primary_color": "negros",
            "brand": "jbl",
            "visible_features": list(reversed(lost.visible_features)),
            "location": "cafeteria CENTRAL",
            "description": (
                "Estuche compacto ovalado con auriculares inalámbricos negros"
            ),
        }
    )

    result = service.evaluate(MatchRequest(lost=lost, found=found))

    assert result.level == MatchLevel.HIGH
    assert result.percentage == 100
    assert len(result.factors) == 8
    assert {factor.name for factor in result.factors} == set(MatchFactorName)
    assert sum(factor.weight for factor in result.factors) == 100
    assert sum(factor.score for factor in result.factors) == result.percentage
    assert all(factor.status == MatchFactorStatus.MATCH for factor in result.factors)
    assert all(factor.explanation for factor in result.factors)
    assert result.warnings == []


def test_brand_conflict_prevents_high_match() -> None:
    lost = _lost_headphones()
    found = MatchableObject(**{**lost.model_dump(), "brand": "Sony"})

    result = service.evaluate(MatchRequest(lost=lost, found=found))

    # A brand contradiction matters even if every other field was copied.
    assert result.percentage == 88
    assert result.level == MatchLevel.POSSIBLE
    brand = next(f for f in result.factors if f.name == MatchFactorName.BRAND)
    assert brand.score == 0
    assert brand.status == MatchFactorStatus.DIFFERENT
    assert any("Marca" in warning for warning in result.warnings)


def test_matching_general_fields_without_distinctive_evidence_is_low() -> None:
    lost = _lost_headphones()
    found = MatchableObject(
        object_type="audífonos deportivos",
        category="electronica",
        primary_color="negro",
        brand="JBL",
        shape="diadema grande",
        visible_features=["cable rojo", "almohadillas grandes"],
        location="Bloque 5",
        event_date=date(2026, 9, 20),
        description="Audífonos deportivos grandes con cable rojo.",
    )

    result = service.evaluate(MatchRequest(lost=lost, found=found))

    assert result.level == MatchLevel.LOW
    assert 0 < result.percentage < 65
    visual = next(
        f for f in result.factors if f.name == MatchFactorName.VISUAL_FEATURES
    )
    assert visual.score == 0
    assert visual.status == MatchFactorStatus.DIFFERENT
    assert result.percentage == round(sum(f.score for f in result.factors))


def test_completely_different_objects_are_low() -> None:
    found = MatchableObject(
        object_type="computador portátil",
        category="electronica",
        primary_color="gris",
        brand="Lenovo",
        shape="rectangular",
        visible_features=["teclado numérico", "pantalla mate"],
        visible_text=["ThinkPad"],
        location="Biblioteca",
        event_date=date(2026, 9, 20),
        description="Computador portátil gris con teclado numérico.",
    )

    result = service.evaluate(MatchRequest(lost=_lost_headphones(), found=found))

    # The shared electronics category alone must not imply the same object.
    assert result.percentage == 10
    assert result.level == MatchLevel.LOW
    object_type = next(
        f for f in result.factors if f.name == MatchFactorName.OBJECT_TYPE
    )
    assert object_type.status == MatchFactorStatus.DIFFERENT


def test_matching_endpoint_returns_structured_evidence() -> None:
    request = MatchRequest(lost=_lost_headphones(), found=_lost_headphones())

    response = client.post(
        "/api/v1/matches/evaluate", json=request.model_dump(mode="json")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["percentage"] == 100
    assert body["level"] == "high"
    assert len(body["factors"]) == 8
    assert sum(factor["score"] for factor in body["factors"]) == body["percentage"]
    assert body["warnings"] == []


def test_unknown_and_blank_values_do_not_earn_points() -> None:
    lost = MatchableObject(
        object_type=" ",
        category="Desconocida",
        primary_color="No visible",
        brand="Sin marca",
        shape="No se distingue",
        visible_features=["", "no identificado"],
        visible_text=["N/A"],
        location="No identificado",
        description=" ",
    )

    result = service.evaluate(MatchRequest(lost=lost, found=lost))

    assert result.percentage == 0
    assert result.level == MatchLevel.LOW
    assert all(f.status == MatchFactorStatus.UNKNOWN for f in result.factors)
    assert all(f.score == 0 for f in result.factors)
    assert result.warnings


def test_missing_evidence_is_not_rescaled_to_a_high_match() -> None:
    lost = MatchableObject(category="electronica", primary_color="negro", brand="JBL")

    result = service.evaluate(MatchRequest(lost=lost, found=lost))

    assert result.percentage == 34
    assert result.level == MatchLevel.LOW
    assert sum(f.score for f in result.factors) == 34
    assert sum(f.status == MatchFactorStatus.UNKNOWN for f in result.factors) == 5


def test_found_date_before_loss_prevents_high_match() -> None:
    lost = _lost_headphones()
    found = MatchableObject(**{**lost.model_dump(), "event_date": date(2026, 8, 31)})

    result = service.evaluate(MatchRequest(lost=lost, found=found))

    assert result.percentage == 94
    assert result.level == MatchLevel.POSSIBLE
    date_factor = next(f for f in result.factors if f.name == MatchFactorName.DATE)
    assert date_factor.score == 0
    assert any("anterior" in warning for warning in result.warnings)


def test_secondary_color_overlap_is_partial() -> None:
    lost = MatchableObject(primary_color="negro", secondary_colors=["rojo"])
    found = MatchableObject(primary_color="roja", secondary_colors=["blanco"])

    result = service.evaluate(MatchRequest(lost=lost, found=found))

    color = next(f for f in result.factors if f.name == MatchFactorName.COLOR)
    assert color.status == MatchFactorStatus.PARTIAL
    assert 0 < color.score < color.weight
    assert result.level == MatchLevel.LOW


def test_matching_endpoint_rejects_invalid_contracts() -> None:
    valid = {"lost": _lost_headphones().model_dump(mode="json"), "found": {}}
    invalid_payloads = [
        {"lost": valid["lost"]},
        {**valid, "unexpected": True},
        {**valid, "found": {"event_date": "2026-02-30"}},
        {**valid, "found": {"invented_attribute": "value"}},
    ]

    for payload in invalid_payloads:
        response = client.post("/api/v1/matches/evaluate", json=payload)
        assert response.status_code == 422, response.text
