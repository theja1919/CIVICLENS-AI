"""
priority.py — Explainable, deterministic priority scoring for CivicLens AI.

IMPORTANT: This is a PROTOTYPE ESTIMATE, not an official risk assessment.
All factors are based on submitted report data only. No external databases,
accident statistics, or government records are consulted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Factor definitions (documented, stable weights)
# ---------------------------------------------------------------------------

# Base scores per category — reflects typical severity ordering
_CATEGORY_BASE: dict[str, int] = {
    "water_leak":          50,
    "pothole":             40,
    "broken_streetlight":  35,
    "garbage":             30,
    "other":               20,
}

# Urgency keywords in description add a fixed bonus
_URGENCY_KEYWORDS = {
    "urgent", "emergency", "danger", "dangerous", "hazard", "hazardous",
    "immediately", "severe", "serious", "critical", "accident", "flooding",
    "blocked", "unsafe", "risk", "injury",
}
_URGENCY_BONUS = 15

# Keyword density bonus (per matched keyword, capped)
_MAX_KEYWORD_BONUS = 25
_KEYWORD_WEIGHT = 5   # per unique keyword match (same as classifier)

# Location bonus — having coordinates means the issue can be dispatched
_LOCATION_BONUS = 5

# Description length signal
_SHORT_DESCRIPTION_PENALTY = -5   # < 20 chars after strip
_RICH_DESCRIPTION_BONUS    =  5   # >= 80 chars

# Max possible score (enforced by min/max clamp)
_MAX_SCORE = 100
_MIN_SCORE = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class PriorityFactor:
    name: str
    value: int          # contribution (positive or negative)
    description: str    # plain-English explanation


@dataclass
class PriorityBreakdown:
    total: int
    factors: list[PriorityFactor] = field(default_factory=list)
    disclaimer: str = (
        "⚠ Prototype estimate only. This score is calculated from submitted "
        "report text and metadata. It is NOT an official risk assessment and "
        "does not reflect verified field surveys, accident statistics, or "
        "government priority rankings."
    )


def compute_priority(
    category: str,
    description: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    keyword_hits: int = 0,
) -> PriorityBreakdown:
    """
    Compute a transparent 0-100 priority score from report data.

    All inputs come from the submitted report — no external data is used.

    Args:
        category:     Report category string.
        description:  Citizen's free-text description.
        latitude:     Optional WGS-84 latitude.
        longitude:    Optional WGS-84 longitude.
        keyword_hits: Number of category keywords found in description
                      (computed by the classifier).

    Returns:
        PriorityBreakdown with total score and per-factor explanations.
    """
    factors: list[PriorityFactor] = []
    import re

    # 1. Category base
    base = _CATEGORY_BASE.get(category, 20)
    factors.append(PriorityFactor(
        name="Category severity",
        value=base,
        description=f"Base score for category '{category}'. "
                    f"Water leaks and potholes rank higher due to typical public-safety impact.",
    ))

    # 2. Urgency keywords
    normalised = re.sub(r"[^\w\s]", " ", description.lower())
    found_urgency = [kw for kw in _URGENCY_KEYWORDS if kw in normalised]
    urgency_val = _URGENCY_BONUS if found_urgency else 0
    if found_urgency:
        factors.append(PriorityFactor(
            name="Urgency language",
            value=urgency_val,
            description=f"Description contains urgency indicator(s): "
                        f"{', '.join(sorted(found_urgency)[:4])}.",
        ))

    # 3. Keyword density
    kw_val = min(_MAX_KEYWORD_BONUS, keyword_hits * _KEYWORD_WEIGHT)
    if kw_val > 0:
        factors.append(PriorityFactor(
            name="Keyword match",
            value=kw_val,
            description=f"{keyword_hits} category-relevant keyword(s) found in description "
                        f"(+{_KEYWORD_WEIGHT} each, capped at {_MAX_KEYWORD_BONUS}).",
        ))

    # 4. Location available
    has_location = latitude is not None and longitude is not None
    if has_location:
        factors.append(PriorityFactor(
            name="Location provided",
            value=_LOCATION_BONUS,
            description="Coordinates supplied — issue can be mapped and dispatched directly.",
        ))

    # 5. Description richness
    desc_len = len(description.strip())
    if desc_len < 20:
        factors.append(PriorityFactor(
            name="Description quality",
            value=_SHORT_DESCRIPTION_PENALTY,
            description=f"Description is very short ({desc_len} chars). "
                        "More detail helps accurate assessment.",
        ))
    elif desc_len >= 80:
        factors.append(PriorityFactor(
            name="Description quality",
            value=_RICH_DESCRIPTION_BONUS,
            description=f"Detailed description ({desc_len} chars) — aids accurate triage.",
        ))

    total = sum(f.value for f in factors)
    total = max(_MIN_SCORE, min(_MAX_SCORE, total))

    return PriorityBreakdown(total=total, factors=factors)
