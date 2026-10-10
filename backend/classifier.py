"""
classifier.py — Rule-based civic issue classifier for CivicLens AI.

IMPORTANT: This is a LOCAL, RULE-BASED keyword classifier.
It does NOT use any AI model, machine-learning API, or image recognition.
Results are labelled as "rule-based suggestions" throughout the application.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

_POTHOLE_KEYWORDS = {
    "pothole", "pot hole", "crater", "road damage", "road crack",
    "asphalt", "pavement", "broken road", "rough road", "road hole",
    "bump", "dip", "sinkhole",
}

_GARBAGE_KEYWORDS = {
    "garbage", "trash", "rubbish", "litter", "waste", "dump", "dumping",
    "overflowing", "bins", "bin", "refuse", "debris", "filth", "dirty",
    "illegal dump", "junk",
}

_STREETLIGHT_KEYWORDS = {
    "streetlight", "street light", "lamp", "lamppost", "light", "lighting",
    "dark", "darkness", "no light", "broken light", "flickering",
    "power outage", "electricity", "bulb",
}

_WATER_KEYWORDS = {
    "water", "leak", "leaking", "flood", "flooding", "puddle", "sewage",
    "sewer", "drain", "pipe", "burst pipe", "water main", "overflow",
    "wet", "moisture", "damp",
}

_CATEGORY_KEYWORD_MAP: dict[str, set[str]] = {
    "pothole": _POTHOLE_KEYWORDS,
    "garbage": _GARBAGE_KEYWORDS,
    "broken_streetlight": _STREETLIGHT_KEYWORDS,
    "water_leak": _WATER_KEYWORDS,
}

# Priority weights: multiplied by hit count to produce score
_PRIORITY_WEIGHTS: dict[str, int] = {
    "pothole": 6,
    "garbage": 4,
    "broken_streetlight": 5,
    "water_leak": 7,
    "other": 3,
}

# Urgency amplifiers in description
_URGENCY_AMPLIFIERS = {
    "urgent", "emergency", "danger", "dangerous", "hazard", "hazardous",
    "immediately", "severe", "serious", "critical", "accident",
}

_MIN_MEANINGFUL_WORDS = 4  # descriptions shorter than this → "Needs review"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ClassifierResult:
    suggestion: str          # Human-readable suggestion label
    priority_score: int      # 0–100
    confidence: str          # "high" | "medium" | "low"
    note: str                # Explanation note shown to user


def classify(description: str, category: str) -> ClassifierResult:
    """
    Classify a civic report using rule-based keyword matching.

    Args:
        description: Free-text description from citizen.
        category: One of pothole / garbage / broken_streetlight /
                  water_leak / other.

    Returns:
        ClassifierResult with a suggestion, priority score, and note.
    """
    normalised = _normalise(description)
    word_count = len(normalised.split())

    # Too short / unclear description → flag for manual review
    if word_count < _MIN_MEANINGFUL_WORDS:
        return ClassifierResult(
            suggestion="Needs review",
            priority_score=_base_priority(category),
            confidence="low",
            note=(
                "Description is too brief for automatic classification. "
                "A staff member will review this report."
            ),
        )

    # Check which categories the description matches
    matched_categories: list[tuple[str, int]] = []
    for cat, keywords in _CATEGORY_KEYWORD_MAP.items():
        hits = _count_hits(normalised, keywords)
        if hits > 0:
            matched_categories.append((cat, hits))

    matched_categories.sort(key=lambda x: x[1], reverse=True)

    urgency_bonus = 10 if _has_urgency(normalised) else 0
    base = _base_priority(category)

    if not matched_categories:
        # Description gave no useful signal
        if category == "other":
            suggestion = "Needs review"
            confidence = "low"
            note = (
                "No recognisable keywords found. "
                "This report has been categorised as 'Other' and will be reviewed."
            )
        else:
            # Trust the selected category
            suggestion = _friendly_name(category)
            confidence = "medium"
            note = (
                f"Category selected by citizen: {_friendly_name(category)}. "
                "No additional keywords found in description."
            )
        score = min(100, base + urgency_bonus)
        return ClassifierResult(
            suggestion=suggestion,
            priority_score=score,
            confidence=confidence,
            note=note,
        )

    top_cat, top_hits = matched_categories[0]
    hit_bonus = min(30, top_hits * _PRIORITY_WEIGHTS.get(top_cat, 3))
    score = min(100, base + hit_bonus + urgency_bonus)

    if top_cat == category or category == "other":
        suggestion = _friendly_name(top_cat)
        confidence = "high" if top_hits >= 3 else "medium"
        note = (
            f"Rule-based suggestion based on description keywords. "
            f"Matched '{_friendly_name(top_cat)}' category "
            f"({top_hits} keyword hit(s))."
        )
    else:
        # Mismatch — report but don't override citizen choice
        suggestion = _friendly_name(category)
        confidence = "medium"
        note = (
            f"Citizen selected '{_friendly_name(category)}'. "
            f"Description keywords also suggest '{_friendly_name(top_cat)}'. "
            "Report filed under the selected category."
        )

    return ClassifierResult(
        suggestion=suggestion,
        priority_score=score,
        confidence=confidence,
        note=note,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase and remove punctuation for keyword matching."""
    return re.sub(r"[^\w\s]", " ", text.lower())


def _count_hits(normalised: str, keywords: set[str]) -> int:
    """Count how many keywords appear in the normalised text."""
    count = 0
    for kw in keywords:
        if kw in normalised:
            count += 1
    return count


def _has_urgency(normalised: str) -> bool:
    for word in _URGENCY_AMPLIFIERS:
        if word in normalised:
            return True
    return False


def _base_priority(category: str) -> int:
    """Default base priority for each category."""
    return {
        "pothole": 40,
        "garbage": 30,
        "broken_streetlight": 35,
        "water_leak": 50,
        "other": 20,
    }.get(category, 20)


def _friendly_name(category: str) -> str:
    return {
        "pothole": "Pothole",
        "garbage": "Garbage / Waste",
        "broken_streetlight": "Broken Streetlight",
        "water_leak": "Water Leak",
        "other": "Other",
    }.get(category, category.replace("_", " ").title())
