from datetime import date, timedelta

import pytest

from app.api.schemas.object_reports import AnalysisCreate, ReportCreate, ReportUpdate
from app.domain.object_reports import (
    AnalysisData,
    ReportAttributes,
    ReportValidationError,
)


def attributes(**changes):
    return ReportAttributes(
        **{
            "object_type": "  Audífonos   Bluetooth ",
            "category": " Electrónica ",
            "primary_color": " NEGRO ",
            "secondary_colors": [" Negro ", " AZUL ", "azul", "  "],
            "brand": " JBL ",
            "description": " Audífonos   con estuche ",
            "location": " Cafetería   central ",
            "event_date": date.today(),
            **changes,
        }
    )


def test_report_normalizes_whitespace_case_colors_and_optional_unknowns():
    report = attributes(shape=" ", private_feature="  Marca   privada ")
    assert report.object_type == "audífonos bluetooth"
    assert report.category == "electrónica"
    assert report.primary_color == "negro"
    assert report.secondary_colors == ("azul",)
    assert report.brand == "JBL"
    assert report.description == "Audífonos con estuche"
    assert report.location == "Cafetería central"
    assert report.shape is None
    assert report.private_feature == "Marca privada"


@pytest.mark.parametrize(
    "changes",
    [
        {"event_date": date.today() + timedelta(days=1)},
        {"object_type": "  "},
        {"description": None},
        {"secondary_colors": None},
        {"secondary_colors": ["x"] * 21},
        {"primary_color": "x" * 101},
        {"location": "a\x00b"},
        {"shape": r"C:\local\photo.png"},
    ],
)
def test_domain_rejects_invalid_attributes_without_frameworks(changes):
    with pytest.raises(ReportValidationError):
        attributes(**changes)


@pytest.mark.parametrize(
    "data",
    [
        {"image_base64": "test-only"},
        {"path": "file:///local/image.png"},
        {"nested": [{"data": "data:image/png;base64,test-only"}]},
        {"local_path": "/tmp/image.png"},
        {"nested": [r"C:\local\image.png"]},
        {"value": b"binary"},
        {"value": float("nan")},
        {"text": "x" * 65537},
    ],
)
def test_extraction_rejects_binary_local_paths_and_non_json(data):
    with pytest.raises(ReportValidationError):
        AnalysisData(extracted_data=data, confidence="alta")


def test_analysis_preserves_json_and_copies_input():
    raw = {"visible_features": ["Estuche ovalado"], "confidence": "media"}
    data = AnalysisData(extracted_data=raw, confidence="media")
    assert data.extracted_data == raw
    raw["visible_features"].append("changed")
    assert data.extracted_data["visible_features"] == ["Estuche ovalado"]


@pytest.mark.parametrize(
    "value",
    [{}, {"description": None}, {"event_date": None}, {"status": None}],
)
def test_patch_requires_a_non_null_editable_field(value):
    with pytest.raises(ValueError):
        ReportUpdate.model_validate(value)


def test_request_schemas_forbid_server_owned_fields():
    with pytest.raises(ValueError):
        AnalysisCreate(
            extracted_data={}, confidence="alta", provider="other", model="client"
        )
    with pytest.raises(ValueError):
        ReportCreate.model_validate({"user_id": "client"})
