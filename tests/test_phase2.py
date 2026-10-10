"""
tests/test_phase2.py — Phase 2 tests:
  - Dashboard statistics (real DB records)
  - Map data with/without coordinates
  - Duplicate detection (within/outside radius, missing coords)
  - Priority score bounds and breakdown
  - Status workflow (valid and invalid transitions)
  - Empty database states
  - API errors
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helper — create a report via API
# ---------------------------------------------------------------------------

def _post(client, **kwargs):
    data = {
        "category": "pothole",
        "description": "Large pothole on Main Street causing vehicle damage",
        **kwargs,
    }
    r = client.post("/reports", data=data, content_type="multipart/form-data")
    assert r.status_code == 201, f"Setup POST failed: {r.get_json()}"
    return r.get_json()


# ===========================================================================
# Statistics endpoint
# ===========================================================================

class TestStats:
    def test_empty_db_returns_zero_counts(self, client):
        data = client.get("/stats").get_json()
        assert data["total_reports"] == 0
        assert data["by_status"]["submitted"] == 0
        assert data["by_status"]["resolved"] == 0
        assert data["high_priority_count"] == 0
        assert data["recent_high_priority"] == []

    def test_stats_total_reflects_real_records(self, client):
        _post(client)
        _post(client, description="Another pothole on Oak Avenue causing problems")
        data = client.get("/stats").get_json()
        assert data["total_reports"] == 2

    def test_stats_submitted_count(self, client):
        _post(client)
        data = client.get("/stats").get_json()
        assert data["by_status"]["submitted"] >= 1

    def test_stats_by_category(self, client):
        _post(client, category="garbage",
              description="Overflowing garbage bins near the park corner")
        _post(client, category="water_leak",
              description="Burst pipe flooding the pavement outside school")
        data = client.get("/stats").get_json()
        assert data["by_category"].get("garbage", 0) >= 1
        assert data["by_category"].get("water_leak", 0) >= 1

    def test_high_priority_counted_correctly(self, client):
        # Water leak with urgency words → score >= 65
        _post(client,
              category="water_leak",
              description="Urgent dangerous burst pipe flooding road emergency now hazardous",
              latitude="51.5", longitude="-0.1")
        data = client.get("/stats").get_json()
        assert data["high_priority_count"] >= 1

    def test_stats_has_required_keys(self, client):
        data = client.get("/stats").get_json()
        for key in ("total_reports", "by_status", "by_category",
                    "high_priority_count", "recent_high_priority"):
            assert key in data, f"Missing key: {key}"

    def test_stats_resolved_count_after_transition(self, client):
        report = _post(client)
        rid = report["id"]
        client.patch(f"/reports/{rid}/status",
                     json={"status": "assigned"})
        client.patch(f"/reports/{rid}/status",
                     json={"status": "in_progress"})
        client.patch(f"/reports/{rid}/status",
                     json={"status": "resolved"})
        data = client.get("/stats").get_json()
        assert data["by_status"]["resolved"] >= 1


# ===========================================================================
# Map data endpoint
# ===========================================================================

class TestMapData:
    def test_empty_db_returns_empty_features(self, client):
        data = client.get("/map-data").get_json()
        assert data["features"] == []
        assert data["total_with_coordinates"] == 0

    def test_report_with_coords_appears_in_map(self, client):
        _post(client, latitude="51.5074", longitude="-0.1278")
        data = client.get("/map-data").get_json()
        assert data["total_with_coordinates"] >= 1
        ids = [f["id"] for f in data["features"]]
        assert len(ids) >= 1

    def test_report_without_coords_excluded_from_features(self, client):
        _post(client)  # no coords
        data = client.get("/map-data").get_json()
        assert data["total_without_coordinates"] >= 1

    def test_map_feature_has_required_fields(self, client):
        _post(client, latitude="40.7128", longitude="-74.0060")
        feature = client.get("/map-data").get_json()["features"][0]
        for key in ("id", "category", "status", "priority_score",
                    "latitude", "longitude", "description_preview"):
            assert key in feature, f"Missing field: {key}"

    def test_map_counts_both_types(self, client):
        _post(client, latitude="51.0", longitude="-0.1")
        _post(client)  # no coords
        data = client.get("/map-data").get_json()
        assert data["total_with_coordinates"] >= 1
        assert data["total_without_coordinates"] >= 1


# ===========================================================================
# Duplicate detection
# ===========================================================================

class TestDuplicates:
    def test_no_duplicates_when_empty(self, client):
        r = _post(client, latitude="51.5074", longitude="-0.1278")
        data = client.get(f"/reports/{r['id']}/duplicates").get_json()
        assert data["duplicates"] == []

    def test_same_location_same_category_is_duplicate(self, client):
        r1 = _post(client,
                   category="pothole",
                   description="Pothole on Elm Street large crater deep damage",
                   latitude="51.5074", longitude="-0.1278")
        r2 = _post(client,
                   category="pothole",
                   description="Another pothole same street same spot big hole",
                   latitude="51.5074", longitude="-0.1278")
        data = client.get(f"/reports/{r1['id']}/duplicates").get_json()
        dup_ids = [d["id"] for d in data["duplicates"]]
        assert r2["id"] in dup_ids

    def test_far_away_report_not_duplicate(self, client):
        r1 = _post(client, category="pothole",
                   description="Pothole on Elm deep crater damaging vehicles daily",
                   latitude="51.5074", longitude="-0.1278")
        # ~1.4 km away — outside 100 m radius
        _post(client, category="pothole",
              description="Pothole far away on another road big damage",
              latitude="51.5200", longitude="-0.1278")
        data = client.get(f"/reports/{r1['id']}/duplicates").get_json()
        assert data["duplicates"] == []

    def test_different_category_not_duplicate(self, client):
        r1 = _post(client, category="pothole",
                   description="Pothole deep crater on Oak Street road surface",
                   latitude="51.5074", longitude="-0.1278")
        _post(client, category="garbage",
              description="Garbage bins overflowing same corner near junction",
              latitude="51.5074", longitude="-0.1278")
        data = client.get(f"/reports/{r1['id']}/duplicates").get_json()
        assert data["duplicates"] == []

    def test_missing_coords_returns_empty_gracefully(self, client):
        r = _post(client)  # no coords
        data = client.get(f"/reports/{r['id']}/duplicates").get_json()
        assert data["has_coordinates"] is False
        assert data["duplicates"] == []

    def test_duplicate_includes_distance(self, client):
        r1 = _post(client, category="pothole",
                   description="Pothole on high street deep dangerous large crater",
                   latitude="51.5074", longitude="-0.1278")
        _post(client, category="pothole",
              description="Same pothole reported again crater causing tyre damage",
              latitude="51.5074", longitude="-0.1278")
        dups = client.get(f"/reports/{r1['id']}/duplicates").get_json()["duplicates"]
        assert "distance_m" in dups[0]

    def test_nonexistent_report_returns_404(self, client):
        assert client.get("/reports/999999/duplicates").status_code == 404

    def test_report_not_duplicate_of_itself(self, client):
        r = _post(client, category="pothole",
                  description="Pothole big deep crater on road surface here",
                  latitude="51.5074", longitude="-0.1278")
        dups = client.get(f"/reports/{r['id']}/duplicates").get_json()["duplicates"]
        self_ids = [d["id"] for d in dups if d["id"] == r["id"]]
        assert self_ids == []


# ===========================================================================
# Haversine geo unit tests
# ===========================================================================

class TestHaversine:
    def test_same_point_is_zero(self):
        from backend.geo import haversine_metres
        assert haversine_metres(51.5, -0.1, 51.5, -0.1) == pytest.approx(0, abs=1)

    def test_known_distance(self):
        from backend.geo import haversine_metres
        # London to Paris ≈ 340 km
        dist = haversine_metres(51.5074, -0.1278, 48.8566, 2.3522)
        assert 330_000 < dist < 350_000

    def test_50m_is_within_100m_radius(self):
        from backend.geo import haversine_metres
        # ~55 m north
        dist = haversine_metres(51.5074, -0.1278, 51.5079, -0.1278)
        assert dist < 100

    def test_200m_is_outside_100m_radius(self):
        from backend.geo import haversine_metres
        # ~111 m per 0.001 degree lat
        dist = haversine_metres(51.5074, -0.1278, 51.5092, -0.1278)
        assert dist > 100


# ===========================================================================
# Priority score and breakdown
# ===========================================================================

class TestPriorityScore:
    def test_priority_endpoint_returns_200(self, client):
        r = _post(client)
        assert client.get(f"/reports/{r['id']}/priority").status_code == 200

    def test_priority_has_breakdown(self, client):
        r = _post(client)
        data = client.get(f"/reports/{r['id']}/priority").get_json()
        assert "breakdown" in data
        assert "factors" in data["breakdown"]
        assert len(data["breakdown"]["factors"]) >= 1

    def test_priority_has_disclaimer(self, client):
        r = _post(client)
        data = client.get(f"/reports/{r['id']}/priority").get_json()
        assert "disclaimer" in data["breakdown"]
        assert len(data["breakdown"]["disclaimer"]) > 20

    def test_priority_score_in_range(self, client):
        r = _post(client)
        data = client.get(f"/reports/{r['id']}/priority").get_json()
        assert 0 <= data["priority_score"] <= 100

    def test_factors_have_required_keys(self, client):
        r = _post(client)
        factors = client.get(f"/reports/{r['id']}/priority").get_json()["breakdown"]["factors"]
        for f in factors:
            assert "name" in f
            assert "value" in f
            assert "description" in f

    def test_water_leak_higher_than_garbage(self):
        from backend.priority import compute_priority
        water = compute_priority("water_leak", "Burst pipe flooding the road pavement now")
        garbage = compute_priority("garbage", "Bins overflowing near the park corner here")
        assert water.total >= garbage.total

    def test_urgency_raises_score(self):
        from backend.priority import compute_priority
        normal = compute_priority("pothole", "Pothole on the road surface needs fixing")
        urgent = compute_priority("pothole",
                                  "Urgent dangerous pothole emergency hazard accident risk")
        assert urgent.total > normal.total

    def test_location_bonus_applied(self):
        from backend.priority import compute_priority
        without = compute_priority("pothole", "Pothole on the road surface here damage")
        with_loc = compute_priority("pothole", "Pothole on the road surface here damage",
                                    latitude=51.5, longitude=-0.1)
        assert with_loc.total > without.total

    def test_priority_score_deterministic(self):
        from backend.priority import compute_priority
        a = compute_priority("water_leak", "Pipe burst flooding pavement urgently now")
        b = compute_priority("water_leak", "Pipe burst flooding pavement urgently now")
        assert a.total == b.total

    def test_priority_clamped_to_100(self):
        from backend.priority import compute_priority
        # Max possible inputs
        result = compute_priority(
            "water_leak",
            "Urgent dangerous emergency critical hazard flooding severe accident " * 5,
            latitude=1.0, longitude=1.0,
            keyword_hits=20,
        )
        assert result.total <= 100

    def test_priority_nonexistent_report_404(self, client):
        assert client.get("/reports/999999/priority").status_code == 404

    def test_priority_breakdown_in_post_response(self, client):
        r = _post(client)
        assert "priority_breakdown" in r
        assert "factors" in r["priority_breakdown"]


# ===========================================================================
# Status workflow
# ===========================================================================

class TestStatusWorkflow:
    def test_initial_status_is_submitted(self, client):
        r = _post(client)
        assert r["status"] == "submitted"

    def test_submitted_to_assigned(self, client):
        r = _post(client)
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "assigned"

    def test_assigned_to_in_progress(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "in_progress"

    def test_in_progress_to_resolved(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        client.patch(f"/reports/{r['id']}/status", json={"status": "in_progress"})
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "resolved"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "resolved"

    def test_resolved_is_terminal(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        client.patch(f"/reports/{r['id']}/status", json={"status": "in_progress"})
        client.patch(f"/reports/{r['id']}/status", json={"status": "resolved"})
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "submitted"})
        assert resp.status_code == 422

    def test_invalid_transition_rejected(self, client):
        r = _post(client)
        # submitted → resolved is NOT valid (must go through assigned first)
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "resolved"})
        assert resp.status_code == 422

    def test_invalid_transition_has_helpful_message(self, client):
        r = _post(client)
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "resolved"})
        detail = resp.get_json()["detail"]
        assert "submitted" in detail.lower() or "resolved" in detail.lower()

    def test_same_status_rejected(self, client):
        r = _post(client)
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "submitted"})
        assert resp.status_code == 422

    def test_unknown_status_rejected(self, client):
        r = _post(client)
        resp = client.patch(f"/reports/{r['id']}/status", json={"status": "warp_speed"})
        assert resp.status_code == 422

    def test_missing_status_body_rejected(self, client):
        r = _post(client)
        resp = client.patch(f"/reports/{r['id']}/status", json={})
        assert resp.status_code == 422

    def test_status_update_reflected_in_get(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        data = client.get(f"/reports/{r['id']}").get_json()
        assert data["status"] == "assigned"

    def test_status_nonexistent_report_404(self, client):
        resp = client.patch("/reports/999999/status", json={"status": "assigned"})
        assert resp.status_code == 404

    def test_assigned_at_set_on_assign(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        data = client.get(f"/reports/{r['id']}").get_json()
        assert data["assigned_at"] is not None

    def test_resolved_at_set_on_resolve(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        client.patch(f"/reports/{r['id']}/status", json={"status": "in_progress"})
        client.patch(f"/reports/{r['id']}/status", json={"status": "resolved"})
        data = client.get(f"/reports/{r['id']}").get_json()
        assert data["resolved_at"] is not None

    def test_status_history_recorded(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        hist = client.get(f"/reports/{r['id']}/history").get_json()["history"]
        assert len(hist) == 1
        assert hist[0]["from_status"] == "submitted"
        assert hist[0]["to_status"] == "assigned"

    def test_full_workflow_history(self, client):
        r = _post(client)
        rid = r["id"]
        client.patch(f"/reports/{rid}/status", json={"status": "assigned"})
        client.patch(f"/reports/{rid}/status", json={"status": "in_progress"})
        client.patch(f"/reports/{rid}/status", json={"status": "resolved"})
        hist = client.get(f"/reports/{rid}/history").get_json()["history"]
        assert len(hist) == 3


# ===========================================================================
# Search / filter
# ===========================================================================

class TestSearchAndFilter:
    def test_search_by_description_keyword(self, client):
        _post(client, description="Pothole near the old oak tree on Elm Street")
        _post(client, description="Broken streetlight flickering outside school yard",
              category="broken_streetlight")
        data = client.get("/reports?search=oak+tree").get_json()
        assert data["total"] >= 1
        assert all("oak" in r["description"].lower() or "tree" in r["description"].lower()
                   for r in data["reports"])

    def test_filter_by_status(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        data = client.get("/reports?status=assigned").get_json()
        for rep in data["reports"]:
            assert rep["status"] == "assigned"


# ===========================================================================
# Empty database and API error states
# ===========================================================================

class TestEdgeCases:
    def test_empty_reports_list(self, client):
        data = client.get("/reports").get_json()
        assert data["total"] == 0
        assert data["reports"] == []

    def test_empty_map_data(self, client):
        data = client.get("/map-data").get_json()
        assert data["total_with_coordinates"] == 0
        assert data["features"] == []

    def test_get_nonexistent_report(self, client):
        assert client.get("/reports/999999").status_code == 404

    def test_get_nonexistent_history(self, client):
        assert client.get("/reports/999999/history").status_code == 404

    def test_limit_boundary(self, client):
        assert client.get("/reports?limit=0").status_code == 422
        assert client.get("/reports?limit=201").status_code == 422

    def test_negative_offset(self, client):
        assert client.get("/reports?offset=-1").status_code == 422
