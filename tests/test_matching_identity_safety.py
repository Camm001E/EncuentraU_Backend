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
    ],
)
def test_provider_terms_remain_compatible_and_symmetric(a, b):
    assert object_type_similarity(a, b) >= 0.35
    assert object_type_similarity(a, b) == object_type_similarity(b, a)


def test_specific_case_uses_do_not_become_synonyms():
    assert object_type_similarity("estuche de audifonos", "cartuchera") == 0


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
