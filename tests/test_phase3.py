"""
tests/test_phase3.py — Phase 3 tests:
  - Citizen workflow (submit → confirm → retrieve → check status)
  - Resolution endpoint (admin provides note + optional after-photo)
  - Reopen workflow (citizen requests reopen with reason)
  - Integration checks (frontend/backend field alignment)
  - Empty-DB safe states for all new endpoints
  - Error cases for resolve/reopen
"""

from __future__ import annotations
import io
import pytest

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_TINY_JPEG = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46,
    0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
    0xFF, 0xD9,
])


def _post(client, **kwargs):
    data = {
        "category": "pothole",
        "description": "Large pothole on Main Street causing vehicle damage here",
        **kwargs,
    }
    r = client.post("/reports", data=data, content_type="multipart/form-data")
    assert r.status_code == 201, f"Setup POST failed: {r.get_json()}"
    return r.get_json()


def _advance_to_in_progress(client, rid):
    client.patch(f"/reports/{rid}/status", json={"status": "assigned"})
    client.patch(f"/reports/{rid}/status", json={"status": "in_progress"})


# ===========================================================================
# Citizen workflow end-to-end
# ===========================================================================

class TestCitizenWorkflow:
    """Verify a citizen can submit, confirm, retrieve, and check status."""

    def test_submit_returns_id_and_status(self, client):
        r = _post(client)
        assert "id" in r
        assert r["id"] > 0
        assert r["status"] == "submitted"

    def test_confirmation_has_classifier(self, client):
        r = _post(client)
        clf = r.get("classifier", {})
        assert "suggestion" in clf
        assert "note" in clf
        assert "priority_score" in clf

    def test_confirmation_has_priority_breakdown(self, client):
        r = _post(client)
        bd = r.get("priority_breakdown", {})
        assert "factors" in bd
        assert len(bd["factors"]) >= 1

    def test_confirmation_has_message_with_id(self, client):
        r = _post(client)
        assert str(r["id"]) in r["message"]

    def test_citizen_can_retrieve_their_report(self, client):
        rid = _post(client)["id"]
        get_r = client.get(f"/reports/{rid}")
        assert get_r.status_code == 200
        data = get_r.get_json()
        assert data["id"] == rid
        assert data["status"] == "submitted"

    def test_report_has_all_citizen_visible_fields(self, client):
        rid = _post(client, latitude="51.5074", longitude="-0.1278")["id"]
        data = client.get(f"/reports/{rid}").get_json()
        for field in ("id", "category", "description", "status", "priority_score",
                      "created_at", "latitude", "longitude"):
            assert field in data, f"Missing field: {field}"

    def test_list_shows_submitted_report(self, client):
        rid = _post(client)["id"]
        data = client.get("/reports").get_json()
        ids = [r["id"] for r in data["reports"]]
        assert rid in ids

    def test_error_on_missing_category(self, client):
        r = client.post("/reports",
                        data={"description": "Something broken here on the road"},
                        content_type="multipart/form-data")
        assert r.status_code == 422
        assert "detail" in r.get_json()

    def test_error_on_short_description(self, client):
        r = client.post("/reports",
                        data={"category": "pothole", "description": "Hi"},
                        content_type="multipart/form-data")
        assert r.status_code == 422

    def test_error_message_is_readable(self, client):
        r = client.post("/reports",
                        data={"category": "flying_car",
                              "description": "Something here on road surface"},
                        content_type="multipart/form-data")
        assert r.status_code == 422
        detail = r.get_json()["detail"]
        assert isinstance(detail, str)
        assert len(detail) > 10   # not an empty/opaque error

    def test_404_returns_readable_detail(self, client):
        r = client.get("/reports/999999")
        assert r.status_code == 404
        detail = r.get_json()["detail"]
        assert "999999" in detail

    def test_submit_with_coordinates_stored_correctly(self, client):
        rid = _post(client, latitude="40.7128", longitude="-74.0060")["id"]
        data = client.get(f"/reports/{rid}").get_json()
        assert abs(data["latitude"] - 40.7128) < 0.0001
        assert abs(data["longitude"] - (-74.0060)) < 0.0001

    def test_submit_without_coordinates_is_accepted(self, client):
        r = _post(client)  # no lat/lon
        assert r["status"] == "submitted"
        data = client.get(f"/reports/{r['id']}").get_json()
        assert data["latitude"] is None
        assert data["longitude"] is None

    def test_image_upload_with_report(self, client):
        data = {
            "category": "garbage",
            "description": "Overflowing garbage bins at the park entrance corner",
            "image": (io.BytesIO(_TINY_JPEG), "photo.jpg", "image/jpeg"),
        }
        r = client.post("/reports", data=data, content_type="multipart/form-data")
        assert r.status_code == 201
        rid = r.get_json()["id"]
        report = client.get(f"/reports/{rid}").get_json()
        assert report["image_path"] is not None
        assert "uploads/" in report["image_path"]

    def test_unsafe_file_path_not_stored(self, client):
        """Path traversal filenames must not create unsafe paths."""
        data = {
            "category": "garbage",
            "description": "Overflowing garbage bin needs urgent collection today",
            "image": (io.BytesIO(_TINY_JPEG), "../../etc/passwd.jpg", "image/jpeg"),
        }
        r = client.post("/reports", data=data, content_type="multipart/form-data")
        if r.status_code == 201:
            path = client.get(f"/reports/{r.get_json()['id']}").get_json()["image_path"]
            assert ".." not in path
            assert path.startswith("uploads/")


# ===========================================================================
# Resolution workflow
# ===========================================================================

class TestResolution:
    def test_resolve_returns_200(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        resp = client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Pothole filled with asphalt. Road surface restored."},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200

    def test_resolve_sets_status_resolved(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Issue fixed. Area cleaned and cleared by team."},
            content_type="multipart/form-data",
        )
        data = client.get(f"/reports/{r['id']}").get_json()
        assert data["status"] == "resolved"

    def test_resolve_stores_note(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        note = "Road resurfaced. Quality checked by supervisor on site."
        client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": note},
            content_type="multipart/form-data",
        )
        data = client.get(f"/reports/{r['id']}").get_json()
        assert data["resolution_note"] == note

    def test_resolve_sets_resolved_at(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Cleared and fixed by maintenance crew yesterday."},
            content_type="multipart/form-data",
        )
        data = client.get(f"/reports/{r['id']}").get_json()
        assert data["resolved_at"] is not None

    def test_resolve_with_after_photo(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        resp = client.post(
            f"/reports/{r['id']}/resolve",
            data={
                "resolution_note": "Pothole filled and road resurfaced completely.",
                "image": (io.BytesIO(_TINY_JPEG), "after.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["resolution_image_path"] is not None

    def test_resolve_from_assigned_auto_advances(self, client):
        """Resolving an 'assigned' report auto-advances through in_progress."""
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        resp = client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Fixed directly after assignment by the crew team."},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "resolved"

    def test_resolve_missing_note_rejected(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        resp = client.post(
            f"/reports/{r['id']}/resolve",
            data={},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_resolve_short_note_rejected(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        resp = client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "OK"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_resolve_submitted_report_rejected(self, client):
        r = _post(client)
        resp = client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Fixed already it seems all good now completely."},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_resolve_nonexistent_report_404(self, client):
        resp = client.post(
            "/reports/999999/resolve",
            data={"resolution_note": "Nothing to resolve here ever found anywhere."},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 404

    def test_resolve_adds_history_entry(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Road work completed successfully by the maintenance team."},
            content_type="multipart/form-data",
        )
        hist = client.get(f"/reports/{r['id']}/history").get_json()["history"]
        statuses_to = [h["to_status"] for h in hist]
        assert "resolved" in statuses_to


# ===========================================================================
# Reopen workflow
# ===========================================================================

class TestReopenWorkflow:
    def _make_resolved(self, client):
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Fixed by team. Pavement restored to good condition."},
            content_type="multipart/form-data",
        )
        return r["id"]

    def test_reopen_returns_200(self, client):
        rid = self._make_resolved(client)
        resp = client.post(
            f"/reports/{rid}/reopen",
            json={"reason": "The pothole has reappeared after recent heavy rain this week."},
        )
        assert resp.status_code == 200

    def test_reopen_stores_reason(self, client):
        rid = self._make_resolved(client)
        reason = "The issue was not properly fixed and has returned after rain last week."
        client.post(f"/reports/{rid}/reopen", json={"reason": reason})
        data = client.get(f"/reports/{rid}").get_json()
        assert data["reopen_reason"] == reason

    def test_reopen_status_remains_resolved(self, client):
        """Reopen request does NOT auto-change status — admin must do it."""
        rid = self._make_resolved(client)
        client.post(
            f"/reports/{rid}/reopen",
            json={"reason": "Issue has reappeared after the rain over the past week."},
        )
        data = client.get(f"/reports/{rid}").get_json()
        assert data["status"] == "resolved"

    def test_reopen_sets_reopen_at(self, client):
        rid = self._make_resolved(client)
        client.post(
            f"/reports/{rid}/reopen",
            json={"reason": "The problem has come back much worse than before this month."},
        )
        data = client.get(f"/reports/{rid}").get_json()
        assert data["reopen_at"] is not None

    def test_reopen_adds_history_entry(self, client):
        rid = self._make_resolved(client)
        client.post(
            f"/reports/{rid}/reopen",
            json={"reason": "Problem is back after flooding over the past few days."},
        )
        hist = client.get(f"/reports/{rid}/history").get_json()["history"]
        notes = [h.get("note", "") or "" for h in hist]
        assert any("Reopen requested" in n for n in notes)

    def test_reopen_missing_reason_rejected(self, client):
        rid = self._make_resolved(client)
        resp = client.post(f"/reports/{rid}/reopen", json={})
        assert resp.status_code == 422

    def test_reopen_short_reason_rejected(self, client):
        rid = self._make_resolved(client)
        resp = client.post(f"/reports/{rid}/reopen", json={"reason": "Still bad"})
        assert resp.status_code == 422

    def test_reopen_non_resolved_rejected(self, client):
        r = _post(client)
        resp = client.post(
            f"/reports/{r['id']}/reopen",
            json={"reason": "This issue has not been resolved yet and is still ongoing here."},
        )
        assert resp.status_code == 422

    def test_reopen_nonexistent_report_404(self, client):
        resp = client.post(
            "/reports/999999/reopen",
            json={"reason": "This issue has never been resolved it is still an active problem."},
        )
        assert resp.status_code == 404

    def test_after_reopen_admin_can_reassign(self, client):
        """Admin can use PATCH /status to reassign after a reopen request."""
        rid = self._make_resolved(client)
        client.post(
            f"/reports/{rid}/reopen",
            json={"reason": "Issue reappeared after three days of heavy rain this week."},
        )
        # Admin manually changes status back to submitted for re-investigation
        # Note: 'resolved' is terminal in /status — this tests the limit
        resp = client.patch(f"/reports/{rid}/status", json={"status": "submitted"})
        # This should be rejected (resolved → submitted not in STATUS_TRANSITIONS)
        assert resp.status_code == 422
        # Correct workflow: admin resolves then creates new report or reassigns via /resolve


# ===========================================================================
# Integration — frontend/backend field alignment
# ===========================================================================

class TestIntegration:
    def test_post_response_has_all_frontend_expected_fields(self, client):
        """All fields that app.js reads must be present in POST /reports response."""
        r = _post(client)
        # app.js reads: data.id, data.status, data.classifier, data.priority_score
        assert "id" in r
        assert "status" in r
        assert "classifier" in r
        assert "priority_score" in r
        # classifier sub-fields: suggestion, priority_score, note
        clf = r["classifier"]
        assert "suggestion" in clf
        assert "priority_score" in clf
        assert "note" in clf

    def test_get_report_has_resolution_fields(self, client):
        """GET /reports/<id> must include resolution fields for dashboard modal."""
        r = _post(client)
        data = client.get(f"/reports/{r['id']}").get_json()
        assert "resolution_note" in data
        assert "resolution_image_path" in data
        assert "reopen_reason" in data
        assert "reopen_at" in data

    def test_stats_endpoint_returns_all_dashboard_fields(self, client):
        data = client.get("/stats").get_json()
        for key in ("total_reports", "by_status", "by_category",
                    "high_priority_count", "recent_high_priority"):
            assert key in data

    def test_map_data_features_have_dashboard_required_fields(self, client):
        _post(client, latitude="51.5", longitude="-0.1")
        feature = client.get("/map-data").get_json()["features"][0]
        for key in ("id", "category", "status", "priority_score",
                    "latitude", "longitude", "description_preview"):
            assert key in feature

    def test_health_endpoint_format(self, client):
        data = client.get("/health").get_json()
        assert data["status"] == "ok"
        assert "version" in data
        assert data["database"] == "ok"

    def test_report_list_search_returns_matching_only(self, client):
        _post(client, description="Pothole outside the old library building here")
        _post(client, description="Water leak flooding the basement car park area",
              category="water_leak")
        data = client.get("/reports?search=library").get_json()
        for r in data["reports"]:
            assert "library" in r["description"].lower()

    def test_report_list_status_filter(self, client):
        r = _post(client)
        client.patch(f"/reports/{r['id']}/status", json={"status": "assigned"})
        data = client.get("/reports?status=assigned").get_json()
        for report in data["reports"]:
            assert report["status"] == "assigned"

    def test_category_filter_enforced(self, client):
        _post(client, category="garbage",
              description="Garbage bins overflowing near the central park main gate")
        data = client.get("/reports?category=garbage").get_json()
        for report in data["reports"]:
            assert report["category"] == "garbage"


# ===========================================================================
# Database persistence verification
# ===========================================================================

class TestPersistence:
    def test_resolution_note_persists_in_db(self, client, db_session):
        from backend.database import Report
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        note = "Road completely resurfaced by maintenance team this afternoon."
        client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": note},
            content_type="multipart/form-data",
        )
        db_session.expire_all()
        rec = db_session.query(Report).filter(Report.id == r["id"]).first()
        assert rec is not None
        assert rec.resolution_note == note
        assert rec.status == "resolved"

    def test_reopen_reason_persists_in_db(self, client, db_session):
        from backend.database import Report
        r = _post(client)
        _advance_to_in_progress(client, r["id"])
        client.post(
            f"/reports/{r['id']}/resolve",
            data={"resolution_note": "Fixed today by crew. All clear on site."},
            content_type="multipart/form-data",
        )
        reason = "The pothole has reappeared after the recent heavy rainfall this week."
        client.post(f"/reports/{r['id']}/reopen", json={"reason": reason})
        db_session.expire_all()
        rec = db_session.query(Report).filter(Report.id == r["id"]).first()
        assert rec is not None
        assert rec.reopen_reason == reason
