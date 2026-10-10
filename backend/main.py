"""
main.py — CivicLens AI Flask application.

Phase 1 Endpoints
-----------------
GET  /health
POST /reports
GET  /reports
GET  /reports/<report_id>

Phase 2 Endpoints
-----------------
GET  /reports/<report_id>/duplicates
PATCH /reports/<report_id>/status
GET  /reports/<report_id>/priority
GET  /stats
GET  /map-data
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.classifier import classify, _count_hits, _CATEGORY_KEYWORD_MAP, _normalise
from backend.config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_IMAGE_TYPES,
    API_VERSION,
    APP_TITLE,
    APP_DESCRIPTION,
    MAX_UPLOAD_SIZE_BYTES,
    UPLOAD_DIR,
)
from backend.database import Report, SessionLocal, StatusHistory, create_tables
from backend.geo import find_nearby_reports, haversine_metres
from backend.priority import compute_priority

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

create_tables()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE_BYTES + 1024 * 64

VALID_CATEGORIES = {"pothole", "garbage", "broken_streetlight", "water_leak", "other"}

# Status workflow: each status maps to the set of statuses it may transition TO
# Reopen is handled via a dedicated /reopen endpoint, not via /status
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "submitted":   {"assigned"},
    "assigned":    {"in_progress", "submitted"},
    "in_progress": {"resolved"},
    "resolved":    set(),                      # terminal via /status; reopen via /reopen
}
ALL_STATUSES = set(STATUS_TRANSITIONS.keys())

DUPLICATE_RADIUS_M: float = 100.0

# CORS — only localhost origins during development.
# Replace with your domain in production.
_ALLOWED_ORIGINS = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    # file:// origin for opening HTML files directly from disk
    "null",
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _db() -> Session:
    return SessionLocal()


def _report_to_dict(r: Report, include_breakdown: bool = False) -> dict:
    d = {
        "id": r.id,
        "category": r.category,
        "description": r.description,
        "latitude": r.latitude,
        "longitude": r.longitude,
        "status": r.status,
        "image_path": r.image_path,
        "priority_score": r.priority_score,
        "classifier_suggestion": r.classifier_suggestion,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "assigned_at": r.assigned_at.isoformat() if r.assigned_at else None,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        # Resolution workflow fields
        "resolution_note": getattr(r, "resolution_note", None),
        "resolution_image_path": getattr(r, "resolution_image_path", None),
        # Reopen workflow fields
        "reopen_reason": getattr(r, "reopen_reason", None),
        "reopen_at": r.reopen_at.isoformat() if getattr(r, "reopen_at", None) else None,
    }
    if include_breakdown and r.priority_breakdown:
        try:
            d["priority_breakdown"] = json.loads(r.priority_breakdown)
        except Exception:
            d["priority_breakdown"] = None
    return d


def _err(msg: str, code: int):
    return jsonify({"detail": msg}), code


def _cors(response):
    """Add CORS headers for localhost-only origins."""
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.after_request
def after_request(response):
    return _cors(response)


@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    resp = app.make_response("")
    resp.status_code = 204
    return _cors(resp)


def _keyword_hits_for(description: str, category: str) -> int:
    """Count keyword matches for the given category."""
    norm = _normalise(description)
    keywords = _CATEGORY_KEYWORD_MAP.get(category, set())
    return _count_hits(norm, keywords)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Return API health and DB connectivity."""
    db = _db()
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    finally:
        db.close()
    return jsonify({"status": "ok", "version": API_VERSION, "database": db_status})


# ---------------------------------------------------------------------------
# POST /reports
# ---------------------------------------------------------------------------

@app.post("/reports")
def create_report():
    """Submit a new civic issue report (multipart/form-data)."""
    category = (request.form.get("category") or "").strip().lower()
    description = (request.form.get("description") or "").strip()
    lat_raw = request.form.get("latitude")
    lon_raw = request.form.get("longitude")

    if not category:
        return _err("Field 'category' is required.", 422)
    if category not in VALID_CATEGORIES:
        return _err(
            f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
            422,
        )
    if not description:
        return _err("Field 'description' is required.", 422)
    if len(description) < 5:
        return _err("Description must be at least 5 characters.", 422)

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    lat_provided = lat_raw is not None and lat_raw.strip() != ""
    lon_provided = lon_raw is not None and lon_raw.strip() != ""

    if lat_provided != lon_provided:
        return _err("Both latitude and longitude must be provided together, or both omitted.", 422)

    if lat_provided:
        try:
            latitude = float(lat_raw)
        except (ValueError, TypeError):
            return _err("Latitude must be a valid number.", 422)
        if not (-90.0 <= latitude <= 90.0):
            return _err("Latitude must be between -90 and 90.", 422)
        try:
            longitude = float(lon_raw)
        except (ValueError, TypeError):
            return _err("Longitude must be a valid number.", 422)
        if not (-180.0 <= longitude <= 180.0):
            return _err("Longitude must be between -180 and 180.", 422)

    # Image upload
    image_path: Optional[str] = None
    image = request.files.get("image")
    if image and image.filename:
        suffix = Path(image.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return _err(f"Unsupported file type '{suffix}'.", 422)
        content_type = image.content_type or ""
        if content_type not in ALLOWED_IMAGE_TYPES:
            return _err(f"Unsupported MIME type '{content_type}'.", 422)
        file_bytes = image.read()
        if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
            return _err(f"Image exceeds maximum size of {MAX_UPLOAD_SIZE_BYTES // (1024*1024)} MB.", 413)
        safe_name = f"{uuid.uuid4().hex}{suffix}"
        dest = UPLOAD_DIR / safe_name
        dest.write_bytes(file_bytes)
        image_path = f"uploads/{safe_name}"

    # Classify + priority
    clf_result = classify(description, category)
    kw_hits = _keyword_hits_for(description, category)
    priority = compute_priority(
        category=category,
        description=description,
        latitude=latitude,
        longitude=longitude,
        keyword_hits=kw_hits,
    )

    breakdown_json = json.dumps({
        "total": priority.total,
        "disclaimer": priority.disclaimer,
        "factors": [
            {"name": f.name, "value": f.value, "description": f.description}
            for f in priority.factors
        ],
    })

    db = _db()
    try:
        report = Report(
            category=category,
            description=description,
            latitude=latitude,
            longitude=longitude,
            image_path=image_path,
            priority_score=priority.total,
            classifier_suggestion=clf_result.suggestion,
            priority_breakdown=breakdown_json,
            status="submitted",
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        return jsonify({
            "id": report.id,
            "status": report.status,
            "category": report.category,
            "priority_score": report.priority_score,
            "classifier": {
                "suggestion": clf_result.suggestion,
                "priority_score": clf_result.priority_score,
                "confidence": clf_result.confidence,
                "note": clf_result.note,
            },
            "priority_breakdown": json.loads(breakdown_json),
            "message": (
                f"Report #{report.id} submitted successfully. "
                "A staff member will review it shortly."
            ),
            "created_at": report.created_at.isoformat() if report.created_at else None,
        }), 201
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /reports
# ---------------------------------------------------------------------------

@app.get("/reports")
def list_reports():
    """Return a paginated list of reports with optional filters."""
    category = request.args.get("category", "").strip().lower() or None
    status = request.args.get("status", "").strip() or None
    search = request.args.get("search", "").strip() or None

    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return _err("'limit' and 'offset' must be integers.", 422)
    if limit < 1 or limit > 200:
        return _err("'limit' must be between 1 and 200.", 422)
    if offset < 0:
        return _err("'offset' must be >= 0.", 422)
    if category and category not in VALID_CATEGORIES:
        return _err(f"Invalid category filter '{category}'.", 422)

    db = _db()
    try:
        query = db.query(Report)
        if category:
            query = query.filter(Report.category == category)
        if status:
            query = query.filter(Report.status == status)
        if search:
            query = query.filter(Report.description.ilike(f"%{search}%"))

        total = query.count()
        reports = query.order_by(Report.created_at.desc()).offset(offset).limit(limit).all()
        return jsonify({
            "total": total,
            "reports": [_report_to_dict(r) for r in reports],
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /reports/<report_id>
# ---------------------------------------------------------------------------

@app.get("/reports/<int:report_id>")
def get_report(report_id: int):
    """Retrieve a single report by ID (includes priority breakdown)."""
    db = _db()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report is None:
            return _err(f"Report #{report_id} not found.", 404)
        return jsonify(_report_to_dict(report, include_breakdown=True))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /reports/<report_id>/duplicates   [Phase 2]
# ---------------------------------------------------------------------------

@app.get("/reports/<int:report_id>/duplicates")
def get_duplicates(report_id: int):
    """
    Find reports of the same category within 100 m of this report.

    Uses Haversine formula. Returns an empty list if the target report
    has no coordinates. Never automatically merges or deletes reports.
    """
    radius = float(request.args.get("radius_m", DUPLICATE_RADIUS_M))

    db = _db()
    try:
        target = db.query(Report).filter(Report.id == report_id).first()
        if target is None:
            return _err(f"Report #{report_id} not found.", 404)

        if target.latitude is None or target.longitude is None:
            return jsonify({
                "report_id": report_id,
                "has_coordinates": False,
                "radius_m": radius,
                "duplicates": [],
                "note": "This report has no coordinates. Duplicate detection requires coordinates.",
            })

        # Query only same-category reports that have coordinates
        candidates = (
            db.query(Report)
            .filter(
                Report.category == target.category,
                Report.latitude.isnot(None),
                Report.longitude.isnot(None),
                Report.id != report_id,
            )
            .all()
        )

        nearby = find_nearby_reports(
            target_lat=target.latitude,
            target_lon=target.longitude,
            candidates=candidates,
            radius_m=radius,
            exclude_id=report_id,
        )

        return jsonify({
            "report_id": report_id,
            "has_coordinates": True,
            "radius_m": radius,
            "duplicates": nearby,
            "note": (
                "Possible duplicates shown by location proximity and category match. "
                "Reports are NOT automatically merged. Admin review required."
            ),
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PATCH /reports/<report_id>/status   [Phase 2]
# ---------------------------------------------------------------------------

@app.route("/reports/<int:report_id>/status", methods=["PATCH"])
def update_status(report_id: int):
    """
    Transition a report's status through the defined workflow.

    Valid transitions:
      submitted → assigned
      assigned  → in_progress | submitted
      in_progress → resolved
      resolved  → (terminal, no further transitions)
    """
    body = request.get_json(silent=True) or {}
    new_status = (body.get("status") or "").strip().lower()
    note = (body.get("note") or "").strip() or None

    if not new_status:
        return _err("Request body must include 'status'.", 422)
    if new_status not in ALL_STATUSES:
        return _err(
            f"Unknown status '{new_status}'. Valid statuses: {', '.join(sorted(ALL_STATUSES))}",
            422,
        )

    db = _db()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report is None:
            return _err(f"Report #{report_id} not found.", 404)

        current = report.status
        if new_status == current:
            return _err(f"Report is already '{current}'.", 422)

        allowed = STATUS_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            return _err(
                f"Cannot transition from '{current}' to '{new_status}'. "
                f"Allowed next statuses: {', '.join(sorted(allowed)) or 'none (terminal state)'}",
                422,
            )

        now = datetime.now(timezone.utc)

        # Record history
        hist = StatusHistory(
            report_id=report.id,
            from_status=current,
            to_status=new_status,
            changed_at=now,
            note=note,
        )
        db.add(hist)

        # Update report
        report.status = new_status
        report.updated_at = now
        if new_status == "assigned":
            report.assigned_at = now
        elif new_status == "resolved":
            report.resolved_at = now

        db.commit()
        db.refresh(report)

        return jsonify({
            "id": report.id,
            "status": report.status,
            "previous_status": current,
            "updated_at": report.updated_at.isoformat(),
            "assigned_at": report.assigned_at.isoformat() if report.assigned_at else None,
            "resolved_at": report.resolved_at.isoformat() if report.resolved_at else None,
            "message": f"Status updated from '{current}' to '{new_status}'.",
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /reports/<report_id>/priority   [Phase 2]
# ---------------------------------------------------------------------------

@app.get("/reports/<int:report_id>/priority")
def get_priority(report_id: int):
    """Return the stored priority score and full factor breakdown."""
    db = _db()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report is None:
            return _err(f"Report #{report_id} not found.", 404)

        breakdown = None
        if report.priority_breakdown:
            try:
                breakdown = json.loads(report.priority_breakdown)
            except Exception:
                breakdown = None

        if breakdown is None:
            # Re-compute on-the-fly for legacy reports without stored breakdown
            kw_hits = _keyword_hits_for(report.description, report.category)
            priority = compute_priority(
                category=report.category,
                description=report.description,
                latitude=report.latitude,
                longitude=report.longitude,
                keyword_hits=kw_hits,
            )
            breakdown = {
                "total": priority.total,
                "disclaimer": priority.disclaimer,
                "factors": [
                    {"name": f.name, "value": f.value, "description": f.description}
                    for f in priority.factors
                ],
            }

        return jsonify({
            "report_id": report_id,
            "priority_score": report.priority_score,
            "breakdown": breakdown,
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /stats   [Phase 2]
# ---------------------------------------------------------------------------

@app.get("/stats")
def get_stats():
    """
    Return dashboard statistics computed from real database records.
    Empty database returns zero counts — no hardcoded values.
    """
    db = _db()
    try:
        total = db.query(func.count(Report.id)).scalar() or 0

        # Status counts
        status_rows = (
            db.query(Report.status, func.count(Report.id))
            .group_by(Report.status)
            .all()
        )
        by_status = {s: c for s, c in status_rows}

        # Category counts
        cat_rows = (
            db.query(Report.category, func.count(Report.id))
            .group_by(Report.category)
            .all()
        )
        by_category = {c: cnt for c, cnt in cat_rows}

        # High-priority: score >= 65
        high_priority = (
            db.query(func.count(Report.id))
            .filter(Report.priority_score >= 65)
            .scalar() or 0
        )

        # Recent: last 5 high-priority reports
        recent_high = (
            db.query(Report)
            .filter(Report.priority_score >= 65)
            .order_by(Report.priority_score.desc(), Report.created_at.desc())
            .limit(5)
            .all()
        )

        return jsonify({
            "total_reports": total,
            "by_status": {
                "submitted":   by_status.get("submitted", 0),
                "assigned":    by_status.get("assigned", 0),
                "in_progress": by_status.get("in_progress", 0),
                "resolved":    by_status.get("resolved", 0),
            },
            "by_category": by_category,
            "high_priority_count": high_priority,
            "recent_high_priority": [_report_to_dict(r) for r in recent_high],
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /map-data   [Phase 2]
# ---------------------------------------------------------------------------

@app.get("/map-data")
def get_map_data():
    """
    Return all reports that have valid coordinates for Leaflet map rendering.
    Reports without coordinates are excluded from the map dataset but counted.
    """
    db = _db()
    try:
        with_coords = (
            db.query(Report)
            .filter(Report.latitude.isnot(None), Report.longitude.isnot(None))
            .all()
        )
        without_coords_count = (
            db.query(func.count(Report.id))
            .filter(Report.latitude.is_(None))
            .scalar() or 0
        )

        features = []
        for r in with_coords:
            features.append({
                "id": r.id,
                "category": r.category,
                "status": r.status,
                "priority_score": r.priority_score,
                "description_preview": r.description[:120] + "…" if len(r.description) > 120 else r.description,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

        return jsonify({
            "features": features,
            "total_with_coordinates": len(features),
            "total_without_coordinates": without_coords_count,
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /reports/<report_id>/history   [Phase 2]
# ---------------------------------------------------------------------------

@app.get("/reports/<int:report_id>/history")
def get_status_history(report_id: int):
    """Return the status change audit trail for a report."""
    db = _db()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report is None:
            return _err(f"Report #{report_id} not found.", 404)
        history = [
            {
                "from_status": h.from_status,
                "to_status": h.to_status,
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
                "note": h.note,
            }
            for h in sorted(report.history, key=lambda x: x.changed_at or datetime.min)
        ]
        return jsonify({"report_id": report_id, "history": history})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Static uploads
# ---------------------------------------------------------------------------

@app.get("/uploads/<path:filename>")
def serve_upload(filename: str):
    return send_from_directory(str(UPLOAD_DIR.resolve()), filename)


# ---------------------------------------------------------------------------
# POST /reports/<report_id>/resolve   [Phase 3]
# ---------------------------------------------------------------------------

@app.post("/reports/<int:report_id>/resolve")
def resolve_report(report_id: int):
    """
    Admin endpoint: mark a report as resolved with a note and optional after-photo.
    Requires the report to already be in_progress status.
    Accepts multipart/form-data with:
      - resolution_note (required, min 5 chars)
      - image (optional after-photo)
    """
    resolution_note = (request.form.get("resolution_note") or "").strip()
    if not resolution_note:
        return _err("Field 'resolution_note' is required.", 422)
    if len(resolution_note) < 5:
        return _err("Resolution note must be at least 5 characters.", 422)

    # Optional after-photo
    resolution_image_path: Optional[str] = None
    image = request.files.get("image")
    if image and image.filename:
        suffix = Path(image.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return _err(f"Unsupported file type '{suffix}'.", 422)
        content_type = image.content_type or ""
        if content_type not in ALLOWED_IMAGE_TYPES:
            return _err(f"Unsupported MIME type '{content_type}'.", 422)
        file_bytes = image.read()
        if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
            return _err("After-photo exceeds maximum size.", 413)
        safe_name = f"resolution_{uuid.uuid4().hex}{suffix}"
        dest = UPLOAD_DIR / safe_name
        dest.write_bytes(file_bytes)
        resolution_image_path = f"uploads/{safe_name}"

    db = _db()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report is None:
            return _err(f"Report #{report_id} not found.", 404)

        # Must be in_progress to resolve via this endpoint
        if report.status not in ("in_progress", "assigned"):
            return _err(
                f"Cannot resolve a report with status '{report.status}'. "
                "Report must be 'assigned' or 'in_progress'.", 422
            )

        now = datetime.now(timezone.utc)
        prev_status = report.status

        # Advance through workflow if needed
        if report.status == "assigned":
            db.add(StatusHistory(
                report_id=report.id, from_status="assigned",
                to_status="in_progress", changed_at=now,
                note="Auto-advanced to in_progress on resolve."
            ))
            report.status = "in_progress"

        db.add(StatusHistory(
            report_id=report.id, from_status=report.status,
            to_status="resolved", changed_at=now,
            note=resolution_note[:255]
        ))

        report.status = "resolved"
        report.resolved_at = now
        report.updated_at = now
        report.resolution_note = resolution_note
        if resolution_image_path:
            report.resolution_image_path = resolution_image_path

        db.commit()
        db.refresh(report)

        return jsonify({
            "id": report.id,
            "status": report.status,
            "previous_status": prev_status,
            "resolved_at": report.resolved_at.isoformat(),
            "resolution_note": report.resolution_note,
            "resolution_image_path": report.resolution_image_path,
            "message": f"Report #{report.id} has been marked as resolved.",
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /reports/<report_id>/reopen   [Phase 3]
# ---------------------------------------------------------------------------

@app.post("/reports/<int:report_id>/reopen")
def reopen_report(report_id: int):
    """
    Citizen endpoint: request that a resolved report be reopened.
    Stores the reason; does NOT automatically change status.
    An admin must then use PATCH /reports/<id>/status to transition.
    Accepts JSON with:
      - reason (required, min 10 chars)
    """
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()

    if not reason:
        return _err("Request body must include 'reason'.", 422)
    if len(reason) < 10:
        return _err("Reopen reason must be at least 10 characters.", 422)

    db = _db()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report is None:
            return _err(f"Report #{report_id} not found.", 404)

        if report.status != "resolved":
            return _err(
                f"Cannot request reopen for a report with status '{report.status}'. "
                "Only resolved reports can be reopened.", 422
            )

        now = datetime.now(timezone.utc)
        report.reopen_reason = reason
        report.reopen_at = now
        report.updated_at = now

        db.add(StatusHistory(
            report_id=report.id,
            from_status="resolved",
            to_status="resolved",  # status unchanged — just a reopen request
            changed_at=now,
            note=f"Reopen requested: {reason[:200]}"
        ))

        db.commit()
        db.refresh(report)

        return jsonify({
            "id": report.id,
            "status": report.status,
            "reopen_reason": report.reopen_reason,
            "reopen_at": report.reopen_at.isoformat(),
            "message": (
                f"Reopen request recorded for Report #{report.id}. "
                "An admin will review and may resubmit or assign the report."
            ),
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(e):
    return _err(f"File too large. Maximum is {MAX_UPLOAD_SIZE_BYTES // (1024*1024)} MB.", 413)

@app.errorhandler(404)
def not_found(e):
    return _err("Endpoint not found.", 404)

@app.errorhandler(405)
def method_not_allowed(e):
    return _err("Method not allowed.", 405)


if __name__ == "__main__":
    app.run(debug=True, port=8000)
