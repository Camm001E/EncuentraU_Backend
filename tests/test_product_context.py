from datetime import date

import pytest

from app.application.matching_service import MatchingService
from app.domain.matching import MatchableObject, MatchRequest
from app.domain.product_context import compare_product_context


def obj(kind, description):
    return MatchableObject(
        object_type=kind,
        description=description,
        category="aseo",
        brand="Marca de prueba",
        primary_color="blanco",
        shape="rectangular",
        location="Recepción",
        event_date=date(2026, 11, 16),
    )


@pytest.mark.parametrize(
    "left,right,description",
    [
        ("jabón facil", "botella dispensadora de limpiador facial", "limpiador facial"),
        ("champú", "frasco de shampoo", "shampoo para cabello"),
        ("crema", "tarro de loción", "loción corporal"),
        ("dentífrico", "tubo de pasta dental", "pasta dental"),
        ("perfume", "frasco", "perfume floral"),
        ("desodorante", "envase", "desodorante"),
    ],
)
def test_product_packaging_candidates_are_symmetric_and_never_certified(
    left, right, description
):
    a, b = obj(left, description), obj(right, description)
    assert compare_product_context(a, b).bridge
    assert compare_product_context(a, b) == compare_product_context(b, a)
    forward = MatchingService().evaluate(MatchRequest(lost=a, found=b))
    reverse = MatchingService().evaluate(MatchRequest(lost=b, found=a))
    assert forward.percentage == reverse.percentage
    assert forward.compatible and forward.percentage >= 60
    if forward.factors[0].score == 0:
        assert forward.level == "possible" and forward.percentage < 85


@pytest.mark.parametrize(
    "left,right,a_desc,b_desc",
    [
        ("jabón", "botella de shampoo", "jabón facial", "shampoo"),
        (
            "botella de limpiador facial",
            "botella de crema",
            "limpiador facial",
            "crema facial",
        ),
        ("frasco de champú", "frasco de acondicionador", "champú", "acondicionador"),
        ("jabón", "dispensador de jabón", "jabón para manos", "jabón facial"),
        ("jabón", "botella de limpiador", "jabón corporal", "limpiador para vajilla"),
        ("crema facial", "frasco de perfume", "crema facial", "perfume"),
    ],
)
def test_different_products_or_uses_are_blocked_even_with_same_brand_colour_shape(
    left, right, a_desc, b_desc
):
    a, b = obj(left, a_desc), obj(right, b_desc)
    assert compare_product_context(a, b).conflict
    for x, y in ((a, b), (b, a)):
        result = MatchingService().evaluate(MatchRequest(lost=x, found=y))
        assert not result.compatible and result.percentage < 60


@pytest.mark.parametrize(
    "left,right,a_desc,b_desc",
    [
        ("anillo", "botella", "anillo", "limpiador facial"),
        ("teléfono", "botella", "limpiador facial", "limpiador facial"),
        ("jabón", "botella", "objeto blanco", "objeto blanco"),
        ("llave", "frasco", "Marca de prueba", "Marca de prueba"),
        ("jabón", "botella", "limpiador facial", "producto de aseo"),
    ],
)
def test_unknown_or_unrelated_descriptions_do_not_activate_bridge(
    left, right, a_desc, b_desc
):
    a, b = obj(left, a_desc), obj(right, b_desc)
    assert not compare_product_context(a, b).bridge
    result = MatchingService().evaluate(MatchRequest(lost=a, found=b))
    assert not result.compatible


def test_real_report_wording_retains_raw_type_score_and_requires_review():
    a = obj("jabón facil", "limpiador facial cetaphil")
    b = obj("botella dispensadora de limpiador facial", "Jabol facial Cetaphil")
    result = MatchingService().evaluate(MatchRequest(lost=a, found=b))
    assert result.compatible and result.level == "possible"
    assert result.factors[0].score == 0
    assert any("envase" in message for message in result.warnings)


def test_explicit_solid_and_liquid_forms_are_not_equivalent():
    a = obj("jabón en barra", "jabón facial en barra")
    b = obj("botella de jabón líquido", "jabón facial líquido")
    assert compare_product_context(a, b).conflict
    assert not MatchingService().evaluate(MatchRequest(lost=a, found=b)).compatible


def test_negated_product_cannot_activate_context_bridge():
    a = obj("jabón", "jabón facial")
    b = obj("botella", "no es jabón facial")
    assert not compare_product_context(a, b).bridge
