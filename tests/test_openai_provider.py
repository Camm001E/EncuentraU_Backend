from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from openai import APIStatusError, APITimeoutError

from app.core.config import Settings
from app.domain.image_analysis import ObjectImageAnalysis
from app.domain.object_reports import ReportValidationError
from app.infrastructure.analysis_errors import ImageAnalysisProviderError
from app.infrastructure.analysis_provider import (
    FallbackImageAnalyzer,
    build_image_analyzer,
)
from app.infrastructure.analysis_receipt import issue_receipt, verify_receipt
from app.infrastructure.openai_image_analyzer import OpenAIImageAnalyzer
from tests.test_ai_endpoint import FakeImageAnalyzer


def result():
    return FakeImageAnalyzer().analyze(
        b"fake-image-content",
        "image/jpeg",
        "Audífonos negros encontrados en la cafetería",
    )


def settings(**kwargs):
    return Settings(
        _env_file=None,
        openai_api_key="fake-key",
        gemini_api_key="fake-key",
        jwt_secret_key="x" * 32,
        **kwargs,
    )


def response(**kwargs):
    data = dict(
        status="completed",
        output=[],
        output_text=result().model_dump_json(),
        model="gpt-5.4-mini-snapshot",
        usage=None,
    )
    data.update(kwargs)
    return SimpleNamespace(**data)


def analyzer(reply=None, error=None):
    client = Mock()
    client.responses.create.return_value = reply or response()
    client.responses.create.side_effect = error
    return OpenAIImageAnalyzer(settings(), client), client


def test_openai_request_and_stable_contract():
    service, client = analyzer()
    actual = service.analyze(b"image", "image/png", "untrusted description")
    assert actual.model_dump() == result().model_dump()
    assert actual._metadata["provider"] == "openai"
    request = client.responses.create.call_args.kwargs
    assert request["store"] is False
    assert request["reasoning"] == {"effort": "high"}
    assert (
        request["input"][0]["content"][1]["image_url"]
        == "data:image/png;base64,aW1hZ2U="
    )
    schema = request["text"]["format"]["schema"]
    assert set(schema["required"]) == set(ObjectImageAnalysis.model_fields)
    assert "_metadata" not in schema["properties"]
    assert client.responses.create.call_count == 1


@pytest.mark.parametrize(
    "reply,reason,allowed",
    [
        (response(status="incomplete"), "incomplete", True),
        (response(output_text="not json"), "invalid_output", True),
        (response(output_text='{"object_detected":"true"}'), "invalid_output", True),
        (
            response(
                output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])]
            ),
            "refusal",
            False,
        ),
    ],
)
def test_invalid_or_refused_results(reply, reason, allowed):
    service, _ = analyzer(reply)
    with pytest.raises(ImageAnalysisProviderError) as error:
        service.analyze(b"image", "image/png", "description")
    assert error.value.reason == reason
    assert error.value.fallback_allowed == allowed


@pytest.mark.parametrize(
    "code,allowed",
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (408, True),
        (409, True),
        (429, True),
        (500, True),
    ],
)
def test_http_failure_classification_and_redaction(code, allowed):
    error = APIStatusError(
        "PRIVATE CREDENTIAL",
        response=httpx.Response(
            code, request=httpx.Request("POST", "https://example.invalid")
        ),
        body=None,
    )
    service, _ = analyzer(error=error)
    with pytest.raises(ImageAnalysisProviderError) as caught:
        service.analyze(b"image", "image/png", "description")
    assert caught.value.fallback_allowed == allowed
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_quota_is_not_hidden_by_fallback():
    error = APIStatusError(
        "private",
        response=httpx.Response(
            429, request=httpx.Request("POST", "https://example.invalid")
        ),
        body={"code": "insufficient_quota"},
    )
    service, _ = analyzer(error=error)
    with pytest.raises(ImageAnalysisProviderError) as caught:
        service.analyze(b"image", "image/png", "description")
    assert not caught.value.fallback_allowed


def test_timeout_allows_fallback():
    service, _ = analyzer(
        error=APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
    )
    with pytest.raises(ImageAnalysisProviderError) as caught:
        service.analyze(b"image", "image/png", "description")
    assert caught.value.fallback_allowed


@pytest.mark.parametrize(
    "allowed,enabled", [(True, True), (True, False), (False, True)]
)
def test_controlled_fallback(allowed, enabled):
    primary, secondary = Mock(), Mock()
    primary.analyze.side_effect = ImageAnalysisProviderError(
        "timeout", fallback_allowed=allowed
    )
    expected = result()
    expected._metadata = {"provider": "gemini", "model": "gemini-test"}
    secondary.analyze.return_value = expected
    service = FallbackImageAnalyzer(primary, secondary if enabled else None)
    if allowed and enabled:
        actual = service.analyze(b"image", "image/png", "description")
        assert actual._metadata["fallback_used"] is True
        assert actual._metadata["provider"] == "gemini"
        secondary.analyze.assert_called_once_with(b"image", "image/png", "description")
    else:
        with pytest.raises(ImageAnalysisProviderError):
            service.analyze(b"image", "image/png", "description")
        secondary.analyze.assert_not_called()
    assert primary.analyze.call_count == 1


def test_primary_success_does_not_call_fallback():
    primary, secondary = Mock(), Mock()
    primary.analyze.return_value = result()
    actual = FallbackImageAnalyzer(primary, secondary).analyze(
        b"image", "image/png", "description"
    )
    assert actual._metadata["fallback_used"] is False
    secondary.analyze.assert_not_called()


def test_both_fail_without_loop_or_partial_result():
    primary, secondary = Mock(), Mock()
    primary.analyze.side_effect = ImageAnalysisProviderError(
        "timeout", fallback_allowed=True
    )
    secondary.analyze.side_effect = ImageAnalysisProviderError("unavailable")
    with pytest.raises(ImageAnalysisProviderError):
        FallbackImageAnalyzer(primary, secondary).analyze(
            b"image", "image/png", "description"
        )
    assert primary.analyze.call_count == secondary.analyze.call_count == 1


def test_selection_and_disabling_fallback():
    service = build_image_analyzer(
        settings(ai_primary_provider="openai", ai_fallback_provider="none")
    )
    assert isinstance(service.primary, OpenAIImageAnalyzer)
    assert service.fallback is None
    service.primary.client.close()
    service = build_image_analyzer(settings(ai_primary_provider="gemini"))
    assert service.primary.__class__.__name__ == "GeminiImageAnalyzer"
    service.primary._client.close()


def test_missing_primary_key_fails_visibly():
    config = settings(ai_primary_provider="openai", ai_fallback_provider="gemini")
    config.openai_api_key = None
    with pytest.raises(HTTPException) as caught:
        build_image_analyzer(config)
    assert caught.value.status_code == 503


def test_receipt_binds_actual_provider_and_evidence():
    item = result()
    item._metadata = {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "fallback_used": False,
    }
    config = settings()
    receipt = issue_receipt(item, config)
    assert verify_receipt(receipt, item.model_dump(), config) == item._metadata
    changed = item.model_dump()
    changed["brand"] = "altered"
    with pytest.raises(ReportValidationError):
        verify_receipt(receipt, changed, config)
    with pytest.raises(ReportValidationError):
        verify_receipt("forged", item.model_dump(), config)


def test_receipt_accepts_flutter_string_normalization():
    item = result()
    item.visible_features = ["  test  ", " "]
    item._metadata = {"provider": "gemini", "model": "gemini-test"}
    receipt = issue_receipt(item, settings())
    data = item.model_dump()
    data["visible_features"] = ["test"]
    assert verify_receipt(receipt, data, settings())["provider"] == "gemini"


@pytest.mark.parametrize("provider,fallback", [("openai", False), ("gemini", True)])
def test_report_persists_verified_provider_once(provider, fallback):
    from datetime import date
    from uuid import uuid4

    from app.api.routes.reports import create_report
    from app.api.schemas.object_reports import ReportCreate

    config = settings(ai_primary_provider="openai")
    item = result()
    item._metadata = {
        "provider": provider,
        "model": "test-model",
        "fallback_used": fallback,
    }
    evidence = item.model_dump()
    evidence["analysis_receipt"] = issue_receipt(item, config)
    body = ReportCreate(
        report_type="lost",
        object_type="audifonos",
        category="electronica",
        description="Objeto de prueba",
        location="Biblioteca",
        event_date=date.today(),
        analysis={"extracted_data": evidence, "confidence": "alta"},
    )
    repo = Mock()

    # Verify before serialization; returning an incomplete record is not needed.
    class Captured(Exception):
        pass

    repo.create.side_effect = Captured
    with pytest.raises(Captured):
        create_report(body, SimpleNamespace(id=uuid4()), repo, config)
    assert repo.create.call_count == 1
    record = repo.create.call_args.args[0]
    assert record.analysis.provider == provider
    assert record.analysis.model == "test-model"
    assert (
        record.analysis.data.extracted_data["analysis_metadata"]["fallback_used"]
        == fallback
    )


def test_forged_receipt_does_not_write_report():
    from datetime import date
    from uuid import uuid4

    from app.api.routes.reports import create_report
    from app.api.schemas.object_reports import ReportCreate

    evidence = result().model_dump()
    evidence["analysis_receipt"] = "forged"
    body = ReportCreate(
        report_type="lost",
        object_type="audifonos",
        category="electronica",
        description="Objeto de prueba",
        location="Biblioteca",
        event_date=date.today(),
        analysis={"extracted_data": evidence, "confidence": "alta"},
    )
    repo = Mock()
    with pytest.raises(ReportValidationError):
        create_report(body, SimpleNamespace(id=uuid4()), repo, settings())
    repo.create.assert_not_called()


@pytest.mark.parametrize(
    "reason,status", [("configuration_or_access", 503), ("connection_or_timeout", 502)]
)
def test_endpoint_provider_error_is_safe_and_not_mislabeled(reason, status):
    from fastapi.testclient import TestClient

    from app.api.dependencies.authentication import get_current_user
    from app.infrastructure.gemini_image_analyzer import get_image_analyzer
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="test-user")
    provider = Mock()
    provider.analyze.side_effect = ImageAnalysisProviderError(reason)
    app.dependency_overrides[get_image_analyzer] = lambda: provider
    try:
        response = TestClient(app).post(
            "/api/v1/ai/analyze",
            data={"description": "test object"},
            files={"image": ("test.png", b"image", "image/png")},
        )
        assert response.status_code == status
        assert "Gemini" not in response.text
        assert "fake-key" not in response.text
    finally:
        app.dependency_overrides.clear()
