from typing import Annotated

from fastapi import Depends, HTTPException

from app.core.config import Settings, get_settings
from app.domain.ai_quota import QuotaExceeded, QuotaUnavailable
from app.infrastructure.database.ai_quota import PostgresAIQuota


class AIQuotaGuard:
    def __init__(self, ledger):
        self.ledger = ledger

    def reserve(self, user_id, units):
        try:
            self.ledger.reserve(user_id, units)
        except QuotaExceeded as exc:
            raise HTTPException(
                429,
                "Se alcanzó el límite de IA. Tus reportes y mensajes siguen disponibles. "
                "Intenta de nuevo cuando se renueve el cupo.",
                headers={
                    "Retry-After": str(exc.retry_after),
                    "Cache-Control": "no-store",
                },
            ) from None
        except QuotaUnavailable:
            raise HTTPException(
                503,
                "La IA está temporalmente en pausa. Tus datos están guardados; "
                "intenta nuevamente en unos minutos.",
                headers={"Retry-After": "60", "Cache-Control": "no-store"},
            ) from None


def get_ai_quota(settings: Annotated[Settings, Depends(get_settings)]):
    return AIQuotaGuard(PostgresAIQuota(settings))
