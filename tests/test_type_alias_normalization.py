from datetime import date

import pytest

from app.application.matching_service import MatchingService
from app.domain.evidence_comparison import object_type_similarity
from app.domain.matching import MatchableObject, MatchRequest


@pytest.mark.parametrize(
    "left,right",
    [
        ("sombrilla", "paraguas plegable"),
        ("sombrillas negras", "paraguas negro"),
        ("billetera", "carteras de bolsillo"),
        ("celular", "smartphones"),
        ("cosmetiquera", "neceseres"),
        ("carpeta", "archivadores"),
    ],
)
def test_type_aliases_use_the_same_normalization_as_input(left, right):
    assert object_type_similarity(left, right) == 1
    assert object_type_similarity(right, left) == 1


@pytest.mark.parametrize("other", ["botella", "billetera", "cartuchera", "teléfono"])
def test_umbrella_alias_does_not_merge_unrelated_objects(other):
    assert object_type_similarity("paraguas plegable", other) == 0


def test_natural_umbrella_descriptions_retrieve_candidate_without_brand_or_analysis():
    common = dict(
        category="accesorio",
        primary_color="negro",
        shape="alargada",
        location="Recepción",
        event_date=date(2026, 11, 16),
    )
    request = MatchRequest(
        lost=MatchableObject(
            object_type="sombrilla",
            description="Se me quedó una sombrilla negra con cordón en el mango.",
            **common,
        ),
        found=MatchableObject(
            object_type="paraguas plegable",
            description=(
                "Hallé un paraguas pequeño cerrado, de tela negra y mango redondo."
            ),
            **common,
        ),
    )
    result = MatchingService().evaluate(request)
    assert result.compatible and result.level == "possible"
    assert 60 <= result.percentage < 85
