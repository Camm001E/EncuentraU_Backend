import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.dependencies.authentication import get_current_user
from app.core.config import get_settings
from app.domain.image_analysis import ObjectImageAnalysis
from app.domain.ports.image_analyzer import ImageAnalyzer
from app.infrastructure.analysis_receipt import issue_receipt
from app.infrastructure.gemini_image_analyzer import (
    ImageAnalysisProviderError,
    get_image_analyzer,
)


class AIAnalysisResponse(ObjectImageAnalysis):
    analysis_metadata: dict | None = None
    analysis_receipt: str | None = None


router = APIRouter(
    prefix="/ai",
    tags=["artificial-intelligence"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post(
    "/analyze",
    response_model=AIAnalysisResponse,
    summary="Analizar la fotografía de un objeto",
)
async def analyze_object_image(
    description: Annotated[
        str,
        Form(
            min_length=3,
            max_length=500,
            description="Descripción escrita por la persona que reporta el objeto.",
        ),
    ],
    image: Annotated[
        UploadFile,
        File(description="Fotografía JPEG, PNG o WEBP del objeto."),
    ],
    analyzer: Annotated[ImageAnalyzer, Depends(get_image_analyzer)],
) -> ObjectImageAnalysis:
    settings = get_settings()
    mime_type = image.content_type or ""

    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato no permitido. Usa JPEG, PNG o WEBP.",
        )

    image_bytes = await image.read(settings.max_image_size_bytes + 1)
    await image.close()

    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fotografía está vacía.",
        )

    if len(image_bytes) > settings.max_image_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"La fotografía supera el límite de {settings.max_image_size_mb} MB."
            ),
        )

    try:
        result = await run_in_threadpool(
            analyzer.analyze,
            image_bytes,
            mime_type,
            description.strip(),
        )
        return AIAnalysisResponse(
            **result.model_dump(),
            analysis_metadata=result._metadata or None,
            analysis_receipt=issue_receipt(result, settings),
        )
    except ImageAnalysisProviderError as exc:
        logger.warning("AI analysis failed reason=%s", exc.reason)
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.reason == "configuration_or_access"
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail=(
                "Revisa la configuración y el acceso del proveedor de IA."
                if exc.reason == "configuration_or_access"
                else "No se pudo analizar la fotografía. Intenta nuevamente."
            ),
        ) from None
