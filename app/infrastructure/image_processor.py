import hashlib
import warnings
from io import BytesIO
from pathlib import PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError

from app.domain.report_images import (
    ImageDimensionsError,
    ImageTooLargeError,
    ImageTypeError,
    ImageValidationError,
    ProcessedImage,
)

FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}
EXTENSIONS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
MAX_SOURCE_PIXELS = 32_000_000
MAX_SOURCE_DIMENSION = 16_384
MAX_OUTPUT_DIMENSION = 4096


class PillowImageProcessor:
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes

    def process(self, data: bytes, filename: str, content_type: str) -> ProcessedImage:
        if not data:
            raise ImageValidationError
        if len(data) > self.max_bytes:
            raise ImageTooLargeError
        if (
            not filename
            or len(filename) > 255
            or any(ord(c) < 32 for c in filename)
            or "/" in filename
            or "\\" in filename
            or ":" in filename
            or filename in {".", ".."}
        ):
            raise ImageValidationError
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data), formats=list(FORMATS)) as source:
                    fmt = source.format
                    if fmt not in FORMATS:
                        raise ImageTypeError
                    mime, extension = FORMATS[fmt]
                    if (
                        content_type.lower().strip() != mime
                        or EXTENSIONS.get(PurePosixPath(filename).suffix.lower()) != fmt
                    ):
                        raise ImageTypeError
                    if (
                        source.width * source.height > MAX_SOURCE_PIXELS
                        or max(source.size) > MAX_SOURCE_DIMENSION
                        or min(source.size) < 1
                    ):
                        raise ImageDimensionsError
                    if getattr(source, "n_frames", 1) != 1:
                        raise ImageValidationError
                    source.verify()
                with Image.open(BytesIO(data), formats=[fmt]) as source:
                    source.load()
                    oriented = ImageOps.exif_transpose(source)
                    mode = "RGB" if fmt == "JPEG" else "RGBA"
                    converted = oriented.convert(mode)
                    converted.thumbnail(
                        (MAX_OUTPUT_DIMENSION, MAX_OUTPUT_DIMENSION),
                        Image.Resampling.LANCZOS,
                    )
                    # Fresh pixels carry no EXIF, XMP, text, ICC or client metadata.
                    clean = Image.new(mode, converted.size)
                    clean.paste(converted)
                    output = BytesIO()
                    options = (
                        {"quality": 88}
                        if fmt in {"JPEG", "WEBP"}
                        else {"optimize": True}
                    )
                    clean.save(output, format=fmt, **options)
                    encoded = output.getvalue()
                    if len(encoded) > self.max_bytes:
                        raise ImageTooLargeError
                    return ProcessedImage(
                        encoded,
                        mime,
                        extension,
                        filename,
                        hashlib.sha256(encoded).hexdigest(),
                        clean.width,
                        clean.height,
                    )
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ImageDimensionsError from None
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
            raise ImageValidationError from None
