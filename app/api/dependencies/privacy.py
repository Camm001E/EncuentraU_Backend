from fastapi import Response

PRIVATE_CACHE_CONTROL = "private, no-store"


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
