"""
tests/test_reports.py — Tests for POST /reports, GET /reports, GET /reports/<id>.
"""

from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(client, **kwargs):
    data = {
        "category": "pothole",
        "description": "Large pothole on Main Street causing vehicle damage",
        **kwargs,
    }
    return client.post("/reports", data=data, content_type="multipart/form-data")


# ---------------------------------------------------------------------------
# Valid submissions
# ---------------------------------------------------------------------------

class TestValidSubmissions:
    def test_submit_returns_201(self, client):
        assert _post(client).status_code == 201

    def test_submit_returns_report_id(self, client):
        data = _post(client).get_json()
        assert "id" in data
        assert isinstance(data["id"], int)
        assert data["id"] > 0

    def test_submit_status_is_submitted(self, client):
        assert _post(client).get_json()["status"] == "submitted"

    def test_submit_all_categories(self, client):
        for cat in ["pothole", "garbage", "broken_streetlight", "water_leak", "other"]:
            r = _post(client, category=cat, description=f"Issue about {cat} on the road here")
            assert r.status_code == 201, f"Failed for category: {cat}"

    def test_submit_with_coordinates(self, client):
        r = _post(client, latitude="40.7128", longitude="-74.0060")
        assert r.status_code == 201

    def test_submit_without_coordinates(self, client):
        assert _post(client).status_code == 201

    def test_classifier_info_present(self, client):
        clf = _post(client).get_json()["classifier"]
        for key in ("suggestion", "priority_score", "confidence", "note"):
            assert key in clf

    def test_priority_score_in_range(self, client):
        score = _post(client).get_json()["priority_score"]
        assert 0 <= score <= 100

    def test_message_contains_id(self, client):
        data = _post(client).get_json()
        assert str(data["id"]) in data["message"]


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------

class TestInvalidInput:
    def test_missing_category(self, client):
        r = client.post("/reports", data={"description": "Missing category here text"},
                        content_type="multipart/form-data")
        assert r.status_code == 422

    def test_missing_description(self, client):
        r = client.post("/reports", data={"category": "pothole"},
                        content_type="multipart/form-data")
        assert r.status_code == 422

    def test_invalid_category(self, client):
        assert _post(client, category="flying_car").status_code == 422

    def test_description_too_short(self, client):
        assert _post(client, description="Hi").status_code == 422

    def test_latitude_out_of_range(self, client):
        assert _post(client, latitude="999", longitude="0").status_code == 422

    def test_longitude_out_of_range(self, client):
        assert _post(client, latitude="0", longitude="999").status_code == 422

    def test_only_latitude_provided(self, client):
        assert _post(client, latitude="40.7128").status_code == 422

    def test_only_longitude_provided(self, client):
        assert _post(client, longitude="-74.0060").status_code == 422


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class TestReportRetrieval:
    def test_get_by_id(self, client):
        rid = _post(client).get_json()["id"]
        r = client.get(f"/reports/{rid}")
        assert r.status_code == 200
        assert r.get_json()["id"] == rid

    def test_get_nonexistent_returns_404(self, client):
        assert client.get("/reports/999999").status_code == 404

    def test_list_returns_200(self, client):
        assert client.get("/reports").status_code == 200

    def test_list_structure(self, client):
        data = client.get("/reports").get_json()
        assert "total" in data
        assert isinstance(data["reports"], list)

    def test_list_count_increases(self, client):
        before = client.get("/reports").get_json()["total"]
        _post(client)
        after = client.get("/reports").get_json()["total"]
        assert after == before + 1

    def test_list_filter_by_category(self, client):
        _post(client, category="garbage", description="Overflowing bins near the park corner")
        data = client.get("/reports?category=garbage").get_json()
        assert data["status_code"] if "status_code" in data else True
        for r in data["reports"]:
            assert r["category"] == "garbage"

    def test_list_invalid_category_filter(self, client):
        assert client.get("/reports?category=flying_car").status_code == 422

    def test_report_has_correct_fields(self, client):
        _post(client, category="water_leak",
              description="Burst pipe flooding the sidewalk urgently right now",
              latitude="51.5074", longitude="-0.1278")
        rid = client.get("/reports").get_json()["reports"][0]["id"]
        data = client.get(f"/reports/{rid}").get_json()
        assert data["category"] == "water_leak"
        assert data["status"] == "submitted"
        assert "created_at" in data
        assert abs(data["latitude"] - 51.5074) < 0.001
        assert abs(data["longitude"] - (-0.1278)) < 0.001


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

class TestDatabasePersistence:
    def test_report_in_db(self, client, db_session):
        from backend.database import Report
        rid = _post(client, description="Persistent pothole on Oak Avenue needs fixing now").get_json()["id"]
        rec = db_session.query(Report).filter(Report.id == rid).first()
        assert rec is not None
        assert rec.category == "pothole"

    def test_multiple_reports_persist(self, client, db_session):
        from backend.database import Report
        ids = [_post(client, description=f"Report {i} pothole damage on road here").get_json()["id"]
               for i in range(3)]
        count = db_session.query(Report).filter(Report.id.in_(ids)).count()
        assert count == 3
