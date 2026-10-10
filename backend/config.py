"""
config.py — Application settings loaded from environment variables / .env file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env if present

# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./civiclens.db")

# ------------------------------------------------------------------
# File uploads
# ------------------------------------------------------------------
UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", "uploads"))
MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "5"))
MAX_UPLOAD_SIZE_BYTES: int = MAX_UPLOAD_SIZE_MB * 1024 * 1024
ALLOWED_IMAGE_TYPES: frozenset[str] = frozenset(
    os.getenv(
        "ALLOWED_IMAGE_TYPES",
        "image/jpeg,image/png,image/gif,image/webp",
    ).split(",")
)
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp"}
)

# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------
API_VERSION: str = "1.0.0"
APP_TITLE: str = "CivicLens AI"
APP_DESCRIPTION: str = (
    "Civic issue reporting API. "
    "Phase 1: reporting, storage, and rule-based classification."
)
CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")
