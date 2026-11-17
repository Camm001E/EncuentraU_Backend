import logging
from time import monotonic

from fastapi import HTTPException

from app.infrastructure.analysis_errors import ImageAnalysisProviderError
from app.infrastructure.gemini_image_analyzer import GeminiImageAnalyzer
from app.infrastructure.openai_image_analyzer import OpenAIImageAnalyzer

logger = logging.getLogger(__name__)


class FallbackImageAnalyzer:
    def __init__(self, primary, fallback=None):
        self.primary = primary
        self.fallback = fallback

    def analyze(self, image_bytes, mime_type, description):
        started = monotonic()
        fallback_used = False
        reason = None
        try:
            result = self.primary.analyze(image_bytes, mime_type, description)
        except ImageAnalysisProviderError as exc:
            if not exc.fallback_allowed or self.fallback is None:
                raise
            reason = exc.reason
            logger.warning("AI fallback activated reason=%s", reason)
            fallback_used = True
            result = self.fallback.analyze(image_bytes, mime_type, description)
        result._metadata.update(
            fallback_used=fallback_used,
            fallback_reason=reason,
            duration_ms=round((monotonic() - started) * 1000),
            analysis_version="visual-v3",
        )
        logger.info(
            "AI analysis provider=%s model=%s fallback=%s duration_ms=%s",
            result._metadata.get("provider"),
            result._metadata.get("model"),
            fallback_used,
            result._metadata["duration_ms"],
        )
        return result


def build_image_analyzer(settings):
    def gemini():
        if (
            not settings.gemini_api_key
            or not settings.gemini_api_key.get_secret_value().strip()
        ):
            raise HTTPException(503, "GEMINI_API_KEY no está configurada.")
        return GeminiImageAnalyzer(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
        )

    if settings.ai_primary_provider == "gemini":
        return FallbackImageAnalyzer(gemini())

    if (
        not settings.openai_api_key
        or not settings.openai_api_key.get_secret_value().strip()
    ):
        raise HTTPException(503, "OPENAI_API_KEY no está configurada.")

    fallback = gemini() if settings.ai_fallback_provider == "gemini" else None

    return FallbackImageAnalyzer(OpenAIImageAnalyzer(settings), fallback)
