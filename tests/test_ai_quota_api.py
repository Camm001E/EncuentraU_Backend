from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.ai_quota import AIQuotaGuard, get_ai_quota
from app.api.dependencies.authentication import get_current_user
from app.domain.ai_quota import QuotaExceeded, QuotaUnavailable
from app.infrastructure.gemini_image_analyzer import get_image_analyzer
from app.main import create_app
from tests.test_visual_review import use_case


@pytest.mark.parametrize(
    "error,status,retry",
    [(QuotaExceeded(45), 429, "45"), (QuotaUnavailable(), 503, "60")],
)
def test_quota_failure_never_calls_paid_provider(error, status, retry):
    app = create_app()
    ledger = Mock()
    ledger.reserve.side_effect = error
    analyzer = Mock()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[get_image_analyzer] = lambda: analyzer
    app.dependency_overrides[get_ai_quota] = lambda: AIQuotaGuard(ledger)
    with TestClient(app) as client:
        result = client.post(
            "/api/v1/ai/analyze",
            data={"description": "Foto de prueba"},
            files={"image": ("photo.jpg", b"photo", "image/jpeg")},
        )
    assert result.status_code == status
    assert result.headers["Retry-After"] == retry
    assert result.headers["Cache-Control"] == "no-store"
    analyzer.analyze.assert_not_called()


def test_cached_comparison_does_not_charge_again():
    review, _, analyzer, _ = use_case()
    quota = Mock()
    review.quota = quota
    user = SimpleNamespace(id="user")
    review("match", user)
    review("match", user)
    quota.reserve.assert_called_once_with("user", 3)
    analyzer.compare.assert_called_once()


def test_denied_comparison_releases_capacity():
    review, _, analyzer, cache = use_case()
    quota = Mock()
    quota.reserve.side_effect = HTTPException(429, "quota")
    review.quota = quota
    with pytest.raises(HTTPException):
        review("match", SimpleNamespace(id="user"))
    assert not cache.inflight
    analyzer.compare.assert_not_called()
    quota.reserve.side_effect = None
    review("match", SimpleNamespace(id="user"))
    analyzer.compare.assert_called_once()
