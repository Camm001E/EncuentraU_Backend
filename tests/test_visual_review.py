from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.dependencies.visual_review import (
    get_visual_pair_analyzer,
    get_visual_review_cache,
)
from app.application.visual_review import ReviewMatchPhotos, VisualReviewCache
from app.core.config import Settings
from app.domain.visual_comparison import DifferenceAudit, VisualComparison
from app.infrastructure.analysis_errors import ImageAnalysisProviderError
from app.infrastructure.visual_pair_analyzer import VisualPairAnalyzer
from tests.ownership_support import workflow as workflow
from tests.test_report_images import photo


def evidence(**changes):
    return VisualComparison(
        **{
            "verdict": "different",
            "identity_evidence": "distinctive",
            "quality_sufficient": True,
            "same_parts_visible": True,
            "agreements": [],
            "contradictions": ["Dos cierres frente a un cierre."],
            "explanation": "La estructura visible es distinta.",
            "suggested_photo": None,
            **changes,
        }
    )


def analyzer():
    fake = Mock(namespace="test-model-v1")
    fake.compare.return_value = (
        evidence(),
        {
            "provider": "openai",
            "model": "test-model",
            "prompt_version": "test-v1",
            "fallback_used": False,
        },
    )
    return fake


@pytest.mark.parametrize(
    "changes",
    [
        {"quality_sufficient": False},
        {"same_parts_visible": False},
        {"contradictions": []},
        {"verdict": "consistent", "identity_evidence": "generic"},
        {"verdict": "consistent", "agreements": ["same color"]},
        {"verdict": "consistent", "agreements": ["scratch", "seam"]},
    ],
)
def test_unsupported_certainty_is_downgraded(changes):
    assert evidence(**changes).conservative().verdict == "uncertain"


def test_specific_agreements_can_remain_consistent():
    assert (
        evidence(
            verdict="consistent", agreements=["scratch", "seam"], contradictions=[]
        )
        .conservative()
        .verdict
        == "consistent"
    )


def test_small_images_do_not_spend_api_calls():
    engine = VisualPairAnalyzer(Settings(_env_file=None))
    engine._request = Mock()
    result, meta = engine.compare([(photo(), "image/png")] * 2)
    assert result.verdict == "uncertain" and not result.quality_sufficient
    assert meta["provider"] == "local"
    engine._request.assert_not_called()


def test_invalid_image_fails_safely():
    with pytest.raises(ImageAnalysisProviderError, match="invalid_image"):
        VisualPairAnalyzer._quality([(b"bad", "image/png")])


@pytest.mark.parametrize("allowed", [True, False])
def test_fallback_only_for_allowed_failures(allowed):
    engine = VisualPairAnalyzer(
        Settings(
            _env_file=None, ai_primary_provider="openai", ai_fallback_provider="gemini"
        )
    )
    engine._request = Mock(
        side_effect=[
            ImageAnalysisProviderError("safe", fallback_allowed=allowed),
            (evidence(verdict="uncertain"), {"provider": "gemini", "model": "test"}),
        ]
    )
    images = [(photo(size=(200, 200)), "image/png")] * 2
    if allowed:
        _, meta = engine.compare(images)
        assert meta["fallback_used"]
        assert [x.args[0] for x in engine._request.call_args_list] == [
            "openai",
            "gemini",
        ]
    else:
        with pytest.raises(ImageAnalysisProviderError):
            engine.compare(images)
        assert engine._request.call_count == 1


def test_cache_expiration_and_capacity():
    cache = VisualReviewCache(capacity=2)
    for i in range(3):
        cache.put(i, {"n": i})
    assert cache.get(0) is None and cache.get(1) == {"n": 1}
    cache.ttl = -1
    cache.put(3, {})
    assert cache.get(3) is None


def upload(ctx, report_id, actor, color="blue"):
    response = ctx.client.put(
        f"/api/v1/reports/{report_id}/image",
        headers=ctx.headers[actor],
        files={
            "image": ("photo.png", photo(size=(240, 240), color=color), "image/png")
        },
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def review_context(workflow):
    ctx = workflow
    fake = analyzer()
    cache = VisualReviewCache()
    ctx.client.app.dependency_overrides[get_visual_pair_analyzer] = lambda: fake
    ctx.client.app.dependency_overrides[get_visual_review_cache] = lambda: cache
    upload(ctx, ctx.lost_id, "A")
    upload(ctx, ctx.found_id, "B", "red")
    return ctx, fake, cache


def request(ctx, actor="A"):
    return ctx.client.post(
        f"/api/v1/matches/{ctx.match_id}/visual-review", headers=ctx.headers[actor]
    )


def test_authorized_review_cached_and_photo_replacement_invalidates(review_context):
    ctx, fake, _ = review_context
    first = request(ctx)
    assert first.status_code == 200, first.text
    assert first.json()["comparison"]["verdict"] == "different"
    assert not first.json()["cached"]
    assert request(ctx).json()["cached"] and fake.compare.call_count == 1
    upload(ctx, ctx.found_id, "B", "green")
    updated = request(ctx)
    assert updated.status_code == 200 and not updated.json()["cached"]
    assert updated.json()["candidate_sha256"] != first.json()["candidate_sha256"]
    assert fake.compare.call_count == 2


@pytest.mark.parametrize("actor", ["C", "inactive"])
def test_unauthorized_review_never_calls_provider(review_context, actor):
    ctx, fake, _ = review_context
    response = request(ctx, actor)
    assert response.status_code in (403, 404)
    fake.compare.assert_not_called()


def test_missing_photo_never_calls_provider(workflow):
    fake = analyzer()
    workflow.client.app.dependency_overrides[get_visual_pair_analyzer] = lambda: fake
    response = request(workflow)
    assert response.status_code == 404
    fake.compare.assert_not_called()


def test_provider_error_is_safe_and_releases_capacity(review_context):
    ctx, fake, cache = review_context
    fake.compare.side_effect = ImageAnalysisProviderError(
        "private-token-must-not-appear"
    )
    response = request(ctx)
    assert response.status_code == 502 and "private-token" not in response.text
    assert not cache.inflight
    fake.compare.side_effect = None
    assert request(ctx).status_code == 200


def use_case():
    match = SimpleNamespace(
        my_report=SimpleNamespace(id="a"), candidate_report=SimpleNamespace(id="b")
    )
    repository = Mock()
    repository.get_by_id_and_user.return_value = match
    refs = [SimpleNamespace(sha256=s, content_type="image/png") for s in ("a", "b")]
    images = Mock()
    images.content.side_effect = lambda id, user: SimpleNamespace(
        data=b"photo", reference=refs[id == "b"]
    )
    images.metadata.side_effect = lambda id, user: refs[id == "b"]
    fake = analyzer()
    cache = VisualReviewCache()
    return ReviewMatchPhotos(repository, images, fake, cache), images, fake, cache


def test_replaced_during_inference_is_not_cached_or_returned():
    review, images, fake, cache = use_case()

    def compare(_):
        images.metadata.side_effect = lambda id, user: SimpleNamespace(
            sha256="replacement"
        )
        return analyzer().compare.return_value

    fake.compare.side_effect = compare
    with pytest.raises(HTTPException) as exc:
        review("id", SimpleNamespace(id="user"))
    assert exc.value.status_code == 409
    assert not cache.entries and not cache.inflight


def test_cached_review_rechecks_current_photos():
    review, images, fake, cache = use_case()
    user = SimpleNamespace(id="user")
    review("id", user)
    images.metadata.side_effect = lambda id, user: SimpleNamespace(sha256="replacement")
    with pytest.raises(HTTPException) as exc:
        review("id", user)
    assert exc.value.status_code == 409 and fake.compare.call_count == 1


def test_duplicate_inflight_is_bounded():
    review, _, fake, cache = use_case()
    user = SimpleNamespace(id="user")
    key = ("user", "id", "a", "b", fake.namespace)
    cache.inflight.add(key)
    with pytest.raises(HTTPException) as exc:
        review("id", user)
    assert exc.value.status_code == 429
    fake.compare.assert_not_called()


def test_opposite_sides_cannot_be_rejected_even_with_model_contradictions():
    result = evidence(
        same_parts_visible=False, contradictions=["Frente estampado, reverso liso."]
    )
    assert result.conservative().verdict == "uncertain"


def test_duplicate_agreements_are_not_distinct_evidence():
    result = evidence(
        verdict="consistent",
        contradictions=[],
        agreements=["Same scratch", " same SCRATCH "],
    )
    assert result.conservative().verdict == "uncertain"


@pytest.mark.parametrize(
    "audit_verdict,expected",
    [
        ("different", "different"),
        ("uncertain", "uncertain"),
        ("consistent", "uncertain"),
    ],
)
def test_negative_verdict_requires_independent_viewpoint_audit(audit_verdict, expected):
    engine = VisualPairAnalyzer(Settings(_env_file=None))
    checked = evidence(
        verdict=audit_verdict,
        agreements=["scratch", "seam"],
        contradictions=[] if audit_verdict == "consistent" else ["shape"],
    )
    checked = DifferenceAudit(**checked.model_dump(), difference_basis="construction")
    engine._request = Mock(return_value=(checked, {}))
    result, meta = engine.verify_difference([], evidence(), {"provider": "gemini"})
    assert result.verdict == expected
    assert meta["verification"] == (
        "confirmed" if expected == "different" else "unconfirmed"
    )
    assert engine._request.call_args.kwargs["verification_claims"]


def test_failed_audit_preserves_candidate_without_unverified_contradictions():
    engine = VisualPairAnalyzer(Settings(_env_file=None))
    engine._request = Mock(side_effect=ImageAnalysisProviderError("safe"))
    result, meta = engine.verify_difference([], evidence(), {"provider": "gemini"})
    assert result.verdict == "uncertain" and not result.contradictions
    assert meta["verification"] == "unavailable"


@pytest.mark.parametrize(
    "basis", ["condition", "appearance_or_viewpoint", "insufficient"]
)
def test_damage_or_viewpoint_cannot_reject_the_same_physical_object(basis):
    engine = VisualPairAnalyzer(Settings(_env_file=None))
    audit = DifferenceAudit(**evidence().model_dump(), difference_basis=basis)
    engine._request = Mock(return_value=(audit, {}))
    result, meta = engine.verify_difference([], evidence(), {"provider": "gemini"})
    assert result.verdict == "uncertain" and not result.contradictions
    assert meta["verification_basis"] == basis


def test_generic_design_needs_two_specific_structural_agreements():
    result = evidence(
        verdict="consistent",
        identity_evidence="generic",
        agreements=["Three cameras in triangle", "Side button below lens"],
        structural_agreements=["Three cameras in triangle", "Side button below lens"],
        contradictions=[],
    )
    assert result.conservative().verdict == "consistent"
    assert (
        result.model_copy(update={"structural_agreements": ["same", " SAME "]})
        .conservative()
        .verdict
        == "uncertain"
    )
    assert (
        result.model_copy(update={"same_parts_visible": False}).conservative().verdict
        == "uncertain"
    )
