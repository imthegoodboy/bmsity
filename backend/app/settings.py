from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    database_path: Path = _path_from_env("DATABASE_PATH", "./bmsitai.db")
    upload_dir: Path = _path_from_env("UPLOAD_DIR", "./uploads")
    report_dir: Path = _path_from_env("REPORT_DIR", "./reports")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    teacher_email: str = os.getenv("TEACHER_EMAIL", "teacher@bmsit.ac.in")
    teacher_password: str = os.getenv("TEACHER_PASSWORD", "bmsit-teacher")
    auth_secret: str = os.getenv("AUTH_SECRET", "change-this-dev-secret")
    auth_token_ttl_minutes: int = int(os.getenv("AUTH_TOKEN_TTL_MINUTES", "720"))


settings = Settings()
