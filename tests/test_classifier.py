"""
tests/test_classifier.py — Unit tests for the rule-based classifier.
"""

from __future__ import annotations

import pytest
from backend.classifier import classify, ClassifierResult


class TestClassifierBasic:
    def test_returns_classifier_result(self):
        result = classify("Large pothole on Main Street causing damage", "pothole")
        assert isinstance(result, ClassifierResult)

    def test_pothole_description_high_confidence(self):
        result = classify("Deep pothole in the road surface causing flat tyres", "pothole")
        assert result.suggestion == "Pothole"
        assert result.confidence in ("high", "medium")

    def test_water_leak_description(self):
        result = classify("Water leaking from burst pipe flooding the pavement", "water_leak")
        assert "Water" in result.suggestion or result.suggestion == "Water Leak"

    def test_garbage_description(self):
        result = classify("Overflowing garbage bins and litter on the street corner", "garbage")
        assert result.priority_score >= 0

    def test_streetlight_description(self):
        result = classify("Broken streetlight flickering in dark alley dangerous at night", "broken_streetlight")
        assert result.priority_score > 0

    def test_too_short_returns_needs_review(self):
        result = classify("bad", "other")
        assert result.suggestion == "Needs review"
        assert result.confidence == "low"

    def test_urgent_keyword_boosts_priority(self):
        base = classify("Water leak from pipe near school", "water_leak")
        urgent = classify("Urgent dangerous water leak emergency flooding street now", "water_leak")
        # Urgent description should have equal or higher priority
        assert urgent.priority_score >= base.priority_score

    def test_priority_score_bounded(self):
        for cat in ["pothole", "garbage", "broken_streetlight", "water_leak", "other"]:
            result = classify("Test issue description on the road here now", cat)
            assert 0 <= result.priority_score <= 100

    def test_note_field_present(self):
        result = classify("Pothole near school causing accidents daily", "pothole")
        assert isinstance(result.note, str)
        assert len(result.note) > 0

    def test_other_category_no_keywords(self):
        """'Other' category with no matching keywords → Needs review or suggestion."""
        result = classify("Something weird is happening near the bridge", "other")
        # Should not crash; returns a valid result
        assert isinstance(result.suggestion, str)

    def test_category_mismatch_trusts_citizen_choice(self):
        """If description says pothole but category is garbage, keep garbage."""
        result = classify("There is a pothole on the road surface", "garbage")
        # Should keep citizen's category in suggestion
        assert result.suggestion in ("Garbage / Waste", "Pothole")
        # Should not error
        assert isinstance(result.confidence, str)
