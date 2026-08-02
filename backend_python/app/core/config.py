from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_secret: str
    jwt_secret: str
    database_url: str
    socket_cors_origins: str

    @staticmethod
    def _env(name: str, default: str) -> str:
        return os.getenv(name, default)

    def __init__(self):
        # MVP defaults
        object.__setattr__(self, "app_secret", self._env("APP_SECRET", "pejuang_aspal_secret_2026"))
        object.__setattr__(self, "jwt_secret", self._env("JWT_SECRET", "dev_jwt_secret_change_me"))
        object.__setattr__(self, "database_url", self._env("DATABASE_URL", "sqlite:///pejuang_asal.sqlite"))
        object.__setattr__(self, "socket_cors_origins", self._env("SOCKET_CORS_ORIGINS", "*"))

