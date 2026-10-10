"""
schemas.py — Pydantic v1 models for request / response validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator


VALID_CATEGORIES = {"pothole", "garbage", "broken_streetlight", "water_leak", "other"}
VALID_STATUSES = {"submitted", "in_progress", "resolved", "closed"}


class ClassifierInfo(BaseModel):
    suggestion: str
    priority_score: int
    confidence: str
    note: str


class ReportResponse(BaseModel):
    id: int
    category: str
    description: str
    latitude: Optional[float]
    longitude: Optional[float]
    status: str
    image_path: Optional[str]
    priority_score: int
    classifier_suggestion: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ReportCreateResponse(BaseModel):
    id: int
    status: str
    category: str
    priority_score: int
    classifier: ClassifierInfo
    message: str
    created_at: datetime

    class Config:
        orm_mode = True


class ReportListResponse(BaseModel):
    total: int
    reports: List[ReportResponse]


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
