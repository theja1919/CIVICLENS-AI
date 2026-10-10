"""
tests/conftest.py — Shared pytest fixtures for Flask + SQLAlchemy.

Uses an in-memory SQLite DB and a temp upload dir for each test function.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Override DB and upload settings BEFORE importing the app
os.environ["DATABASE_URL"] = "sqlite://"   # in-memory

from backend.database import Base, SessionLocal  # noqa: E402
from backend.main import app as flask_app       # noqa: E402
import backend.main as main_module              # noqa: E402
import backend.config as config_module          # noqa: E402


@pytest.fixture(scope="function")
def tmp_upload_dir(tmp_path):
    """Temporary upload directory per test."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    return upload_dir


@pytest.fixture(scope="function")
def db_engine():
    """Fresh in-memory SQLite engine per test function."""
    from sqlalchemy import create_engine
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """DB session bound to the in-memory test DB."""
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session, tmp_upload_dir, monkeypatch):
    """
    Flask test client with:
    - In-memory SQLite (via monkeypatched SessionLocal)
    - Temp upload directory
    """
    # Patch upload directory
    monkeypatch.setattr(config_module, "UPLOAD_DIR", tmp_upload_dir)
    monkeypatch.setattr(main_module, "UPLOAD_DIR", tmp_upload_dir)

    # Patch SessionLocal so the app uses our test session
    def patched_session():
        return db_session

    monkeypatch.setattr(main_module, "_db", patched_session)

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
