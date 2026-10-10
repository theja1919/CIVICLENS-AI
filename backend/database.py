"""
database.py — SQLAlchemy setup for CivicLens AI.
Uses SQLite for persistent storage.
"""

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./civiclens.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    status = Column(String(30), nullable=False, default="submitted")
    image_path = Column(String(255), nullable=True)
    priority_score = Column(Integer, nullable=False, default=0)
    classifier_suggestion = Column(String(100), nullable=True)
    # JSON-serialised priority breakdown stored as text
    priority_breakdown = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    # Resolution details (set when admin marks resolved)
    resolution_note = Column(Text, nullable=True)
    resolution_image_path = Column(String(255), nullable=True)
    # Reopen workflow (set when citizen requests reopening)
    reopen_reason = Column(Text, nullable=True)
    reopen_at = Column(DateTime(timezone=True), nullable=True)

    history = relationship(
        "StatusHistory", back_populates="report", cascade="all, delete-orphan"
    )


class StatusHistory(Base):
    """Audit trail of every status transition for a report."""
    __tablename__ = "status_history"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    from_status = Column(String(30), nullable=False)
    to_status = Column(String(30), nullable=False)
    changed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    note = Column(String(255), nullable=True)

    report = relationship("Report", back_populates="history")


def create_tables() -> None:
    """Create all tables if they don't exist, then add any missing columns."""
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """
    Add columns that were introduced after the initial schema creation.
    SQLite does not support DROP COLUMN or complex ALTER TABLE, but ADD COLUMN
    is safe to call multiple times — we skip columns that already exist.
    """
    import sqlite3 as _sqlite3
    from sqlalchemy import inspect as _inspect

    # Only needed for SQLite file databases
    db_url = DATABASE_URL
    if not db_url.startswith("sqlite:///"):
        return  # in-memory or non-SQLite — schema handled by create_all

    db_path = db_url.replace("sqlite:///", "")
    if db_path.startswith("./"):
        db_path = db_path[2:]

    try:
        conn = _sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(reports)")
        existing = {row[1] for row in cur.fetchall()}

        additions = [
            ("priority_breakdown",      "TEXT"),
            ("assigned_at",             "TIMESTAMP"),
            ("resolved_at",             "TIMESTAMP"),
            ("resolution_note",         "TEXT"),
            ("resolution_image_path",   "VARCHAR(255)"),
            ("reopen_reason",           "TEXT"),
            ("reopen_at",               "TIMESTAMP"),
        ]
        for col, typ in additions:
            if col not in existing:
                cur.execute(f"ALTER TABLE reports ADD COLUMN {col} {typ}")

        # Ensure status_history table exists (older DBs may not have it)
        cur.execute("""CREATE TABLE IF NOT EXISTS status_history (
            id         INTEGER PRIMARY KEY,
            report_id  INTEGER NOT NULL REFERENCES reports(id),
            from_status VARCHAR(30) NOT NULL,
            to_status   VARCHAR(30) NOT NULL,
            changed_at  TIMESTAMP,
            note        VARCHAR(255)
        )""")

        conn.commit()
        conn.close()
    except Exception:
        pass  # Non-fatal: tests use in-memory DB; production uses full create_all


def get_db():
    """Dependency: yields a DB session and closes it afterwards."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
