"""
Settings, read from environment variables or a .env file next to this file.

    API_KEYS        comma-separated keys the client's website uses to send data
                    (header: X-API-Key). Required for the /api/v1 endpoints.
    ADMIN_PASSWORD  password for the staff dashboard and editor. If empty, no
                    login is asked (fine on your own computer, never online).
    PUBLIC_URL      address of this server as seen by users, used to build the
                    edit links returned to the website (default http://localhost:8000).
    DATA_DIR        where the database lives (default ./data).
    HOST / PORT     where the server listens (default 127.0.0.1:8000).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE / ".env")

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")
DATA_DIR = Path(os.getenv("DATA_DIR", BASE / "data"))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key() -> str:
    """Signs login cookies. Generated once and kept in DATA_DIR."""
    env = os.getenv("SECRET_KEY")
    if env:
        return env
    path = DATA_DIR / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


SECRET_KEY = _secret_key()
