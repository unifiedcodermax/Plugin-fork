"""Application settings, loaded from environment / .env.

All knobs live here so the rest of the codebase can depend on a
single typed object instead of reading os.environ ad-hoc.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Runtime environment.

    `dev` enables pretty logs and reloads. `prod` switches to JSON
    logs and strict defaults. `test` mutes I/O and forces a
    deterministic JWT secret.
    """

    dev = "dev"
    prod = "prod"
    test = "test"


class Settings(BaseSettings):
    """Top-level engine configuration.

    Values resolve in this order (highest priority first):
      1. Process environment (``PLANARA_*``).
      2. ``.env`` file in the project root.
      3. Defaults declared on this class.

    The ``PLANARA_`` prefix keeps engine vars from colliding with
    whatever else lives in the user's shell.
    """

    model_config = SettingsConfigDict(
        env_prefix="PLANARA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Environment.dev

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)

    log_level: str = "INFO"
    log_json: bool | None = None
    """Force JSON logs on/off. ``None`` means: JSON in prod, pretty elsewhere."""

    jwt_secret: SecretStr = SecretStr("change-me-in-production")
    jwt_ttl_minutes: int = Field(default=480, ge=1)
    jwt_algorithm: str = "HS256"

    db_url: str = "sqlite:///./planara.db"

    @property
    def is_prod(self) -> bool:
        return self.env is Environment.prod

    @property
    def is_test(self) -> bool:
        return self.env is Environment.test

    @property
    def use_json_logs(self) -> bool:
        if self.log_json is not None:
            return self.log_json
        return self.is_prod

    @property
    def project_root(self) -> Path:
        # planara_engine/src/planara_engine/core/settings.py -> repo/planara_engine
        return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so repeated calls don't re-parse ``.env``. Tests can
    bust the cache via ``get_settings.cache_clear()``.
    """

    return Settings()
