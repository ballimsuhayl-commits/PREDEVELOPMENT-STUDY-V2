from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAC_", env_file=".env", extra="ignore")

    # If false, /api/check will refuse to call Nominatim and require lat/lon
    allow_nominatim: bool = False

    # SQLite path
    sqlite_path: str = "municipality_check.db"

    # Data folders
    data_dir: str = "data"


settings = Settings()
