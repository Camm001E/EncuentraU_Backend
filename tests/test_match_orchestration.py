from datetime import date
from uuid import uuid4

import pytest

from app.application.matching_service import MatchingService
from app.application.object_matches import to_matchable_object
from app.domain.matching import MatchRequest
from app.domain.object_reports import (
    AnalysisData,
    ImageAnalysis,
    ObjectReport,
    ReportAttributes,
    ReportType,
)


def report(*, extracted=None, **changes):
    report_id = uuid4()
    return ObjectReport(
        id=report_id,
        user_id=uuid4(),
        report_type=ReportType.LOST,
        attributes=ReportAttributes(
            **{
                "object_type": "Audífonos",
                "category": "electronica",
                "description": "Audífonos negros",
                "location": "Cafetería",
                "event_date": date.today(),
                **changes,
            }
        ),
        analysis=(
            ImageAnalysis(
                id=uuid4(),
                report_id=report_id,
                provider="gemini",
                model="test-model",
                data=AnalysisData(extracted_data=extracted, confidence="alta"),
            )
            if extracted is not None
            else None
        ),
    )


def test_declared_attributes_take_precedence_over_image_analysis():
    result = to_matchable_object(
        report(
            primary_color="negro",
            secondary_colors=["azul"],
            brand="JBL",
            shape="ovalada",
            private_feature="Detalle privado",
            extracted={
                "object_type": "Otro objeto",
                "category": "otro",
                "primary_color": "blanco",
                "secondary_colors": ["rojo"],
                "brand": "Sony",
                "shape": "rectangular",
                "visible_features": ["diadema ajustable"],
                "visible_text": ["JBL"],
            },
        )
    )
    assert result.object_type == "audífonos" and result.category == "electronica"
    assert result.primary_color == "negro" and result.secondary_colors == ["azul"]
    assert result.brand == "JBL" and result.shape == "ovalada"
    assert result.visible_features == ["diadema ajustable"]
    assert result.visible_text == ["JBL"]
    assert "private_feature" not in result.model_dump()


def test_visual_analysis_complements_missing_user_attributes():
    result = to_matchable_object(
        report(
            extracted={
                "primary_color": "negro",
                "secondary_colors": ["azul", "azul"],
                "brand": "JBL",
                "shape": "ovalada",
                "visible_features": [" almohadillas ", "almohadillas"],
                "visible_text": ["JBL"],
            }
        )
    )
    assert result.primary_color == "negro" and result.secondary_colors == ["azul"]
    assert result.brand == "JBL" and result.shape == "ovalada"
    assert result.visible_features == ["almohadillas"]
    assert result.visible_text == ["JBL"]


@pytest.mark.parametrize(
    "extracted",
    [
        None,
        {},
        {
            "primary_color": ["negro"],
            "secondary_colors": "azul",
            "brand": 42,
            "shape": {"text": "ovalada"},
            "visible_features": [None, 7, {}, ""],
            "visible_text": "No es una lista",
        },
        {
            "primary_color": "x" * 101,
            "brand": "x" * 101,
            "shape": "x" * 501,
            "secondary_colors": ["x" * 101],
            "visible_features": ["x" * 2001],
        },
    ],
)
def test_absent_or_malformed_visual_fields_do_not_break_matching(extracted):
    result = to_matchable_object(report(extracted=extracted))
    assert result.primary_color is None and result.secondary_colors == []
    assert result.brand is None and result.shape is None
    assert result.visible_features == [] and result.visible_text == []


def test_full_report_description_is_supported_without_truncation():
    description = "Audífonos " * 400
    result = to_matchable_object(report(description=description))
    assert result.description == description.strip()
    assert (
        MatchingService().evaluate(MatchRequest(lost=result, found=result)).level
        == "high"
    )
