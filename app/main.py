from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth_errors import register_auth_error_handlers
from app.api.report_errors import register_report_error_handlers
from app.api.routes.ai import router as ai_router
from app.api.routes.auth import router as auth_router
from app.api.routes.database import router as database_router
from app.api.routes.matches import router as matches_router
from app.api.routes.reports import router as reports_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description=(
            "API de análisis visual y coincidencias inteligentes para EncuentraU."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials="*" not in settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_auth_error_handlers(app)
    register_report_error_handlers(app)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "phase": "phase-1",
            "model": settings.gemini_model,
        }

    app.include_router(ai_router, prefix=settings.api_prefix)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(matches_router, prefix=settings.api_prefix)
    app.include_router(reports_router, prefix=settings.api_prefix)
    app.include_router(database_router)
    return app


app = create_app()
