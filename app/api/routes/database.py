from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.infrastructure.database.engine import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health/database", summary="Comprobar disponibilidad de PostgreSQL")
def database_health(
    available: Annotated[bool, Depends(check_database_connection)],
) -> dict[str, str]:
    if not available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base de datos no está disponible.",
        )
    return {"status": "ok", "database": "postgresql"}
