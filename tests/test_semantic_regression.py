"""Real sanitized observations are data, never production matching rules."""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.application.matching_service import MatchingService
from app.domain.matching import (
    MatchableObject,
    MatchFactorGroup,
    MatchFactorStatus,
    MatchLevel,
    MatchRequest,
)
from app.domain.matching_vocabulary import COLOURS
from app.domain.semantic_normalization import normalize, word
from app.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "matching" / "observed_views.json"


def _views():
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fields = set(MatchableObject.model_fields)
    return [
        MatchableObject(
            **{
                key: value for key, value in record["analysis"].items() if key in fields
            },
            description=record["description"],
            location="Biblioteca central, mesa 4",
            event_date=date(2026, 10, 18),
        )
        for record in records
    ]


@pytest.mark.parametrize("lost,found", [(0, 1), (2, 3), (4, 5)])
def test_observed_same_object_is_high_from_different_views(lost, found):
    views = _views()
    result = MatchingService().evaluate(
        MatchRequest(lost=views[lost], found=views[found])
    )
    assert result.compatible
    assert result.level == MatchLevel.HIGH
    assert result.percentage >= 85
    assert result.evidence_coverage >= 80


@pytest.mark.parametrize("lost,found", [(0, 3), (2, 1)])
def test_observed_similar_but_different_object_is_never_high(lost, found):
    views = _views()
    result = MatchingService().evaluate(
        MatchRequest(lost=views[lost], found=views[found])
    )
    assert result.compatible
    assert result.level != MatchLevel.HIGH
    assert result.percentage < 85


@pytest.mark.parametrize("lost,found", [(0, 5), (2, 5), (4, 1), (4, 3)])
def test_observed_incompatible_objects_stay_low_despite_identical_context(lost, found):
    views = _views()
    result = MatchingService().evaluate(
        MatchRequest(lost=views[lost], found=views[found])
    )
    assert not result.compatible
    assert result.level == MatchLevel.LOW
    assert result.percentage <= 29
    assert result.context_percentage == 100


def test_real_counterparts_rank_first_with_a_five_point_margin():
    views = _views()
    service = MatchingService()
    matrix = [
        [
            service.evaluate(MatchRequest(lost=views[i], found=views[j])).percentage
            for j in (1, 3, 5)
        ]
        for i in (0, 2, 4)
    ]
    assert matrix[0][0] >= matrix[0][1] + 5 > matrix[0][2]
    assert matrix[1][1] >= matrix[1][0] + 5 > matrix[1][2]
    assert matrix[2][2] > max(matrix[2][:2])


@pytest.mark.parametrize("lost", [0, 2, 4])
@pytest.mark.parametrize("found", [1, 3, 5])
def test_observed_matrix_is_symmetric_and_formula_matches_factors(lost, found):
    views = _views()
    service = MatchingService()
    result = service.evaluate(MatchRequest(lost=views[lost], found=views[found]))
    reversed_result = service.evaluate(
        MatchRequest(lost=views[found], found=views[lost])
    )
    assert result == reversed_result
    groups = {}
    weights = {}
    for group in MatchFactorGroup:
        comparable = [
            f
            for f in result.factors
            if f.group == group and f.status != MatchFactorStatus.UNKNOWN
        ]
        weights[group] = sum(f.evaluable_weight for f in comparable)
        groups[group] = (
            sum(f.score for f in comparable) / weights[group] * 100
            if weights[group]
            else 0
        )
    percentage = round(
        groups[MatchFactorGroup.IDENTITY] * 0.8 + groups[MatchFactorGroup.CONTEXT] * 0.2
    )
    assert result.percentage == (
        percentage if result.compatible else min(29, percentage)
    )
    assert result.evidence_coverage == round(
        weights[MatchFactorGroup.IDENTITY] * 0.8
        + weights[MatchFactorGroup.CONTEXT] * 0.2,
        2,
    )
    assert result.identity_percentage == round(groups[MatchFactorGroup.IDENTITY], 2)
    assert result.context_percentage == round(groups[MatchFactorGroup.CONTEXT], 2)


def test_fixture_contains_only_sanitized_observations_and_descriptions():
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(records) == 6
    analysis_fields = {
        "object_detected",
        "object_type",
        "category",
        "primary_color",
        "secondary_colors",
        "brand",
        "shape",
        "visible_features",
        "visible_text",
        "image_quality",
        "confidence",
        "requires_another_photo",
        "warnings",
    }
    for record in records:
        assert set(record) == {"analysis", "description"}
        assert set(record["analysis"]) == analysis_fields
    content = FIXTURE.read_text(encoding="utf-8")
    assert not any(
        marker in content
        for marker in (
            "@",
            "C:\\",
            "http://",
            "https://",
            "eyJ",
            "AIza",
            "password",
            "token",
            "sha256",
        )
    )


def test_colour_names_can_be_permuted_without_changing_the_matrix():
    # A bijection preserves sameness/difference, not any particular palette.
    colours = sorted(COLOURS)
    replacements = dict(zip(colours, colours[1:] + colours[:1], strict=True))

    def relabel(value):
        if isinstance(value, str):
            return re.sub(
                r"\w+",
                lambda match: replacements.get(word(normalize(match[0])), match[0]),
                value,
            )
        if isinstance(value, list):
            return [relabel(item) for item in value]
        if isinstance(value, dict):
            return {key: relabel(item) for key, item in value.items()}
        return value

    original = _views()
    changed = [
        MatchableObject.model_validate(relabel(view.model_dump(mode="json")))
        for view in original
    ]
    service = MatchingService()
    for lost in (0, 2, 4):
        for found in (1, 3, 5):
            before = service.evaluate(
                MatchRequest(lost=original[lost], found=original[found])
            )
            after = service.evaluate(
                MatchRequest(lost=changed[lost], found=changed[found])
            )
            assert before.percentage == after.percentage
            assert before.level == after.level
            assert before.compatible == after.compatible
            assert before.evidence_coverage == after.evidence_coverage
            assert [(f.name, f.score, f.status) for f in before.factors] == [
                (f.name, f.score, f.status) for f in after.factors
            ]


def test_http_evaluation_preserves_semantic_result_without_a_provider_call():
    views = _views()
    request = MatchRequest(lost=views[0], found=views[1])
    expected = MatchingService().evaluate(request).model_dump(mode="json")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/matches/evaluate", json=request.model_dump(mode="json")
        )
    assert response.status_code == 200
    assert response.json() == expected
