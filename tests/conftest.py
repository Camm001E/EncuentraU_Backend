from unittest.mock import patch

from app.core.config import Settings, get_settings


def pytest_configure() -> None:
    # Prime the shared settings cache before collection imports app.main.
    # Tests must never load .env or use real provider/database credentials.
    settings = Settings(_env_file=None, gemini_api_key=None, database_url=None)
    get_settings.cache_clear()
    with patch("app.core.config.Settings", return_value=settings):
        get_settings()
