"""Require fastening evidence before naming an ambiguous decorative badge."""

from app.domain.image_analysis import ObjectImageAnalysis
from app.domain.semantic_normalization import normalize

_BADGE_TYPES = {
    "pin",
    "pines",
    "chapa",
    "chapas",
    "insignia",
    "insignias",
    "prendedor",
    "prendedores",
    "broche",
    "broches",
}
_OTHER_USES = {"cabello", "pelo", "puerta", "cerradura", "industrial", "metalica"}
_FASTENERS = {
    "alfiler",
    "alfileres",
    "aguja",
    "agujas",
    "imperdible",
    "imperdibles",
    "pasador",
    "pasadores",
    "enganche",
    "enganches",
}
_UNSUPPORTED = {
    "no",
    "sin",
    "oculto",
    "oculta",
    "parece",
    "posible",
    "posiblemente",
    "ilustracion",
    "dibujo",
    "estampado",
    "patron",
    "motivo",
    "simula",
}
_PHOTO_REQUEST = (
    "El frente decorado no permite confirmar el tipo de objeto. "
    "Añade una foto del reverso o del mecanismo de sujeción."
)


def review_badge_identification(
    analysis: ObjectImageAnalysis,
) -> tuple[ObjectImageAnalysis, bool]:
    """Do not promote artwork/outline alone into a pin or badge identification.

    This checks the provider's reported evidence, not the image pixels. It does
    not infer a mirror, prove the evidence is true, or affect other families.
    """
    kind = set(normalize(analysis.object_type).split())
    if not analysis.object_detected or not kind & _BADGE_TYPES or kind & _OTHER_USES:
        return analysis, False
    for feature in analysis.visible_features:
        words = set(normalize(feature).split())
        if words & _FASTENERS and not words & _UNSUPPORTED:
            return analysis, False
    warnings = list(analysis.warnings)
    if _PHOTO_REQUEST not in warnings:
        warnings.append(_PHOTO_REQUEST)
    return analysis.model_copy(
        update={
            "object_type": "objeto decorativo de tipo no confirmado",
            "confidence": "media"
            if analysis.confidence == "alta"
            else analysis.confidence,
            "requires_another_photo": True,
            "warnings": warnings,
        }
    ), True
