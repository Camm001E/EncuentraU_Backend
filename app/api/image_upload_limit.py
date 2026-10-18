import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.domain.report_images import ImageTooLargeError

MULTIPART_OVERHEAD_BYTES = 65_536


class ImageUploadLimit:
    def __init__(self, app: ASGIApp, *, prefix: str, max_bytes: int):
        self.app = app
        self.path = re.compile(re.escape(prefix) + r"/reports/[^/]+/image/?\Z")
        self.limit = max_bytes + MULTIPART_OVERHEAD_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "PUT"
            or not self.path.fullmatch(scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.limit:
                raise ImageTooLargeError
            return message

        # Multipart parsers may translate a receive exception to HTTP 400. Check
        # honest Content-Length before parsing and enforce streaming bounds too.
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > self.limit:
            response = JSONResponse(
                {"detail": ImageTooLargeError.message}, status_code=413
            )
            await response(scope, receive, send)
            return
        await self.app(scope, limited_receive, send)
