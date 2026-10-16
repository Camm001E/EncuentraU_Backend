from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ObjectCategory = Literal[
    "electronica",
    "llaves",
    "documentos",
    "bolsos",
    "ropa",
    "accesorios",
    "otro",
]
ImageQuality = Literal["mala", "regular", "buena"]
ConfidenceLevel = Literal["baja", "media", "alta"]


class ObjectImageAnalysis(BaseModel):
    """Stable JSON contract returned by the visual-analysis provider."""

    model_config = ConfigDict(extra="forbid")

    object_detected: bool = Field(
        description="Indica si existe un objeto principal claramente visible."
    )
    object_type: str | None = Field(
        description="Nombre específico y normalizado del objeto en español."
    )
    category: ObjectCategory = Field(description="Categoría general normalizada.")
    primary_color: str | None = Field(
        description="Color principal visible en español y en minúsculas."
    )
    secondary_colors: list[str] = Field(
        default_factory=list,
        description="Otros colores visibles relevantes.",
    )
    brand: str | None = Field(
        description="Marca únicamente cuando el logotipo o texto sea legible."
    )
    shape: str | None = Field(description="Forma general visible del objeto.")
    visible_features: list[str] = Field(
        default_factory=list,
        description="Rasgos físicos comprobables en la fotografía.",
    )
    visible_text: list[str] = Field(
        default_factory=list,
        description="Texto no sensible que resulte útil para identificar el objeto.",
    )
    image_quality: ImageQuality = Field(
        description="Calidad de la imagen para realizar el análisis."
    )
    confidence: ConfidenceLevel = Field(
        description="Confianza orientativa del análisis visual."
    )
    requires_another_photo: bool = Field(
        description="Indica si se recomienda solicitar una fotografía adicional."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Problemas como desenfoque, reflejos, obstrucciones o varios objetos."
        ),
    )
