from datetime import date

import pytest

from app.application.matching_service import MatchingService
from app.domain.evidence_comparison import object_type_similarity
from app.domain.matching import MatchableObject, MatchRequest
from app.domain.semantic_normalization import description_features


@pytest.mark.parametrize(
    "text",
    [
        "Objeto reportado para identificar sus caracteristicas visibles.",
        "Foto del objeto encontrado para analisis",
        "Imagen de prueba del producto perdido",
    ],
)
def test_reporting_boilerplate_is_not_identity(text):
    assert not description_features(text, frozenset())


@pytest.mark.parametrize(
    "a,b",
    [
        ("cartera", "billetera"),
        ("estuche", "cartuchera"),
        ("cosmetiquera", "neceser"),
        ("archivador", "carpeta"),
        ("smartphone", "telefono movil"),
        ("telefono celular", "telefono movil"),
        ("estuche", "neceser"),
        ("funda de auriculares", "estuche de auriculares"),
        ("bolsita con cremallera", "neceser"),
        ("bolsita con cierre", "cartuchera"),
    ],
)
def test_provider_terms_remain_compatible_and_symmetric(a, b):
    assert object_type_similarity(a, b) >= 0.35
    assert object_type_similarity(a, b) == object_type_similarity(b, a)


def test_specific_case_uses_do_not_become_synonyms():
    assert object_type_similarity("estuche de audifonos", "cartuchera") == 0
    assert (
        object_type_similarity("bolsita con cremallera para auriculares", "cartuchera")
        == 0
    )


@pytest.mark.parametrize(
    "other", ["bolsa de compras", "bolso con cremallera", "bolsita"]
)
def test_zip_pouch_alias_does_not_generalize_other_bags(other):
    assert object_type_similarity(other, "neceser") == 0
    assert object_type_similarity("neceser", other) == 0


def test_context_without_descriptive_evidence_never_establishes_high_identity():
    obj = MatchableObject(
        object_type="botella",
        primary_color="azul",
        shape="cilindrica",
        location="Campus",
        event_date=date(2026, 1, 1),
    )
    result = MatchingService().evaluate(MatchRequest(lost=obj, found=obj))
    assert result.percentage < 85
    assert any("evidencia descriptiva" in w for w in result.warnings)


def test_boilerplate_cannot_inflate_score():
    a = MatchableObject(
        object_type="billetera",
        primary_color="negro",
        visible_features=["costura roja diagonal"],
        location="Campus",
    )
    b = a.model_copy(update={"visible_features": ["costura azul vertical"]})
    service = MatchingService()
    plain = service.evaluate(MatchRequest(lost=a, found=b))
    text = "Objeto reportado para identificar sus caracteristicas visibles."
    generic = service.evaluate(
        MatchRequest(
            lost=a.model_copy(update={"description": text}),
            found=b.model_copy(update={"description": text}),
        )
    )
    assert plain.percentage == generic.percentage
    assert generic.percentage < 85


@pytest.mark.parametrize("modifier", ["alargado", "plano", "curvo", "cilindrico"])
@pytest.mark.parametrize("contour", ["ovalado", "rectangular"])
def test_different_geometry_dimensions_are_not_contradictions(modifier, contour):
    from app.domain.evidence_comparison import feature_pair
    from app.domain.semantic_normalization import feature

    left, right = feature(f"puerto {modifier}"), feature(f"puerto {contour}")
    forward, reverse = feature_pair(left, right), feature_pair(right, left)
    assert forward == reverse
    assert not forward.contradictions
    assert forward.similarity < 1  # Compatible dimensions are not synonyms.


@pytest.mark.parametrize(
    "left,right", [("circular", "rectangular"), ("triangular", "ovalado")]
)
def test_incompatible_contours_still_conflict_even_with_shared_proportion(left, right):
    from app.domain.evidence_comparison import feature_pair
    from app.domain.semantic_normalization import feature

    a, b = feature(f"puerto {left} alargado"), feature(f"puerto {right} alargado")
    for comparison in (feature_pair(a, b), feature_pair(b, a)):
        assert comparison.similarity == 0
        assert comparison.contradictions == (
            "Geometrías explícitas diferentes en un mismo rasgo.",
        )


def test_power_bank_descriptions_do_not_invent_geometry_conflict():
    from app.domain.evidence_comparison import compare_features
    from app.domain.semantic_normalization import features

    left = features(
        [
            "anillo circular gris en la parte superior",
            "pequeño indicador o conector alargado en la parte inferior",
            "esquinas redondeadas",
        ]
    )
    right = features(
        [
            "círculo en relieve en la parte superior",
            "pequeño indicador o puerto ovalado en la parte inferior",
        ]
    )
    result = compare_features(left, right)
    assert result == compare_features(right, left)
    assert not result.contradictions
    assert result.similarity < 1
