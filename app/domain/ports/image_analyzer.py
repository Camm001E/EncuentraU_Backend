from typing import Protocol

from app.domain.image_analysis import ObjectImageAnalysis


class ImageAnalyzer(Protocol):
    def analyze(
        self,
        image_bytes: bytes,
        mime_type: str,
        description: str,
    ) -> ObjectImageAnalysis:
        """Analyze an object image and return the stable domain contract."""
