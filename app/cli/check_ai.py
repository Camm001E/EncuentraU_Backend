"""Explicit, bounded live checks; never imported by the ordinary test suite."""

import argparse
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.config import Settings
from app.domain.matching_version import CURRENT_SCORING_VERSION
from app.infrastructure.analysis_provider import build_image_analyzer


def main():
    parser = argparse.ArgumentParser(description="Prueba explícita de análisis visual")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", action="store_true")
    source.add_argument("--image", type=Path)
    parser.add_argument("--provider", choices=["openai", "gemini"], required=True)
    parser.add_argument("--description", default="Objeto de prueba sobre fondo claro")
    parser.add_argument(
        "--output", type=Path, default=Path("build/ai-validation/result.json")
    )
    args = parser.parse_args()
    settings = Settings()
    settings.ai_primary_provider = args.provider
    settings.ai_fallback_provider = "none"
    if args.synthetic:
        image = Image.new("RGB", (512, 512), "white")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((160, 110, 350, 420), radius=25, fill="navy")
        draw.rectangle((225, 85, 285, 110), fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data, mime = buffer.getvalue(), "image/png"
    else:
        with args.image.open("rb") as file:
            data = file.read(settings.max_image_size_bytes + 1)
        if len(data) > settings.max_image_size_bytes:
            parser.error("La imagen supera el límite configurado.")
        with Image.open(io.BytesIO(data)) as image:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
                image.format
            )
            image.verify()
        if mime is None:
            parser.error("Usa PNG, JPEG o WEBP.")
    # Private evidence artifacts must remain under ignored build/.
    output = args.output.resolve()
    if not output.is_relative_to(Path("build").resolve()):
        parser.error("El resultado debe guardarse dentro de build/.")
    try:
        result = build_image_analyzer(settings).analyze(data, mime, args.description)
    except Exception:
        print(
            "La prueba no terminó: revisa configuración, cuota o disponibilidad. "
            "No se muestran datos privados."
        )
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "metadata": result._metadata,
                "comparator_version": CURRENT_SCORING_VERSION,
                "evidence": result.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "provider": result._metadata["provider"],
                "model": result._metadata["model"],
                "fallback_used": False,
                "duration_ms": result._metadata["duration_ms"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
