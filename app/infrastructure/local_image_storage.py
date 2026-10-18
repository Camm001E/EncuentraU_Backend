import os
import re
import tempfile
from pathlib import Path

from app.domain.report_images import ImageNotFoundError, ImageUnavailableError

SAFE_KEY = re.compile(r"[a-f0-9]{32}\.(?:jpg|png|webp)\Z")


class LocalImageStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        if not SAFE_KEY.fullmatch(key):
            raise ImageUnavailableError
        path = self.root / key
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ImageUnavailableError
        return path

    def write(self, key: str, data: bytes) -> None:
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self._path(key)
            if target.exists():
                raise ImageUnavailableError
            with tempfile.NamedTemporaryFile(
                dir=self.root, suffix=".tmp", delete=False
            ) as f:
                temporary = Path(f.name)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, target)
        except OSError:
            raise ImageUnavailableError from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    raise ImageUnavailableError from None

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise ImageNotFoundError from None
        except OSError:
            raise ImageUnavailableError from None

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            raise ImageUnavailableError from None
