# CivicLens AI — Hackathon Project

> A civic issue reporting and management system.
> Citizens report potholes, garbage, broken streetlights, and water leaks via a
> mobile-friendly form. Admins manage reports on a live dashboard with map,
> priority scoring, duplicate detection, and a status workflow.

> ⚠️ **This is a hackathon demo.** The admin dashboard has no authentication.
> Do not expose it as a production system without adding auth and HTTPS.

---

## Quick Start

```powershell
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows
# source .venv/bin/activate         # Linux / macOS

# 2. Install dependencies
pip install flask sqlalchemy python-dotenv pytest

# 3. (Optional) Load fictional demo data
python seed_data.py                  # idempotent — safe to run multiple times
python seed_data.py --status         # show counts only
python seed_data.py --dry-run        # print what would be inserted

# 4. Start the backend API (port 8000)
python -m flask --app backend.main run --debug --host 0.0.0.0 --port 8000

# 5. Start the frontend (port 3000)
python -m http.server 3000 --directory frontend

# 6. Open in browser
#   Citizen form    → http://localhost:3000/index.html
#   Admin dashboard → http://localhost:3000/dashboard.html
```

---

## Project Structure

```
civiclens/
├── backend/
│   ├── main.py          Flask app — all API routes
│   ├── database.py      SQLAlchemy ORM + auto-migration
│   ├── classifier.py    Rule-based keyword classifier (no AI/API key)
│   ├── priority.py      Explainable deterministic priority scoring
│   ├── geo.py           Haversine distance for duplicate detection
│   └── config.py        Settings (DATABASE_URL, UPLOAD_DIR, limits)
├── frontend/
│   ├── index.html       Citizen reporting form
│   ├── style.css        Citizen form styles
│   ├── app.js           Citizen form JS (validation, geolocation, upload)
│   ├── dashboard.html   Admin dashboard (demo — no auth)
│   ├── dashboard.css    Dashboard styles
│   └── dashboard.js     Dashboard JS (Leaflet, live API, workflow)
├── tests/
│   ├── conftest.py      Flask test client + in-memory SQLite fixtures
│   ├── test_health.py           2 tests
│   ├── test_classifier.py      11 tests
│   ├── test_reports.py         29 tests
│   ├── test_uploads.py          8 tests
│   ├── test_phase2.py          60 tests
│   └── test_phase3.py          46 tests   ← citizen workflow, resolve, reopen
├── seed_data.py         Fictional demo data (idempotent)
├── live_check.py        HTTP smoke tests (run against live server)
├── .env.example         All config options documented
├── requirements.txt
└── README.md
```

---

## API Reference

### Core (Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | API health + DB connectivity |
| `POST` | `/reports` | Submit report (multipart/form-data) |
| `GET`  | `/reports` | List (filter: `category`, `status`, `search`; paginate: `limit`, `offset`) |
| `GET`  | `/reports/<id>` | Get single report with all fields |
| `GET`  | `/uploads/<filename>` | Serve uploaded images |

### Dashboard (Phase 2)

| Method | Path | Description |
|--------|------|-------------|
| `GET`   | `/stats` | KPIs: total, by-status, by-category, high-priority |
| `GET`   | `/map-data` | Reports with coordinates for Leaflet |
| `GET`   | `/reports/<id>/duplicates` | Same-category within 100 m (Haversine) |
| `PATCH` | `/reports/<id>/status` | Advance workflow status |
| `GET`   | `/reports/<id>/priority` | Score + factor breakdown + disclaimer |
| `GET`   | `/reports/<id>/history` | Full status audit trail |

### Resolution & Reopen (Phase 3)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/reports/<id>/resolve` | Admin: mark resolved with note + optional after-photo |
| `POST` | `/reports/<id>/reopen`  | Citizen: request reopen with reason (status unchanged) |

---

## POST /reports — Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `category` | string | ✓ | `pothole`, `garbage`, `broken_streetlight`, `water_leak`, `other` |
| `description` | string | ✓ | Min 5 characters |
| `latitude` | float | – | -90 to 90; must pair with longitude |
| `longitude` | float | – | -180 to 180; must pair with latitude |
| `image` | file | – | JPEG/PNG/WebP/GIF, max 5 MB |

---

## Status Workflow

```
submitted → assigned → in_progress → resolved
                                         ↓
                                   (citizen requests reopen via POST /reopen)
                                         ↓
                               admin reviews reopen_reason
                                         ↓
                               admin uses PATCH /status to reassign
```

- Invalid transitions → `422` with a readable error message.
- `assigned_at` and `resolved_at` stored automatically.
- Every transition recorded in `status_history`.
- POST `/resolve` accepts `assigned` or `in_progress` (auto-advances if needed).
- POST `/reopen` records reason and timestamp but does **not** change status.

---

## Priority Score

Scores range **0–100**, calculated from description text and metadata.

| Factor | Max pts | Notes |
|--------|---------|-------|
| Category base | 50 | water_leak 50 > pothole 40 > streetlight 35 > garbage 30 > other 20 |
| Urgency keywords | +15 | urgent, emergency, dangerous, flooding, hazardous, etc. |
| Keyword density | +25 | Category-specific terms matched in description |
| Location provided | +5 | Coordinates enable direct dispatch |
| Description quality | ±5 | Short (<20 chars) −5; detailed (≥80 chars) +5 |

> ⚠️ **Prototype estimate only.** Based on submitted text and metadata only.
> NOT an official risk assessment. Does NOT reflect government surveys,
> accident statistics, or verified field conditions.

---

## Classifier Disclaimer

- Category classification uses **rule-based keyword matching** only.
- It is **NOT AI image recognition**.
- It is **NOT connected to any government department**.
- No authority is automatically notified when a report is submitted.

---

## Running Tests

```powershell
# All 154 tests
pytest

# Verbose
pytest -v

# Phase 3 only (citizen workflow, resolve, reopen)
pytest tests/test_phase3.py -v

# Live HTTP smoke tests (requires server running on port 8000)
python live_check.py
```

**Test results (verified):**

| File | Tests | Status |
|------|-------|--------|
| test_health.py | 2 | ✅ pass |
| test_classifier.py | 11 | ✅ pass |
| test_reports.py | 29 | ✅ pass |
| test_uploads.py | 8 | ✅ pass |
| test_phase2.py | 60 | ✅ pass |
| test_phase3.py | 46 | ✅ pass |
| **Total** | **154** | **✅ all pass** |

---

## Demo Sequence (2-minute walkthrough)

1. **Seed data** — `python seed_data.py` inserts 8 fictional reports.
2. **Open citizen form** (`http://localhost:3000`) — submit a water leak with the
   Detect Location button, add a description, click Submit. Note the report ID in
   the confirmation.
3. **Open dashboard** (`http://localhost:3000/dashboard.html`) — see KPI counters
   update. The new report appears in the list.
4. **Map tab** — click the new marker. Popup shows category, status, priority.
   Click "View details" to open the modal.
5. **Modal — Priority Breakdown** — scroll to see each scored factor and the
   disclaimer ("prototype estimate only").
6. **Modal — Duplicate Check** — if a nearby same-category report exists, it
   appears here with distance in metres.
7. **Modal — Update Status** — click "Mark as Assigned", then "Mark as In Progress".
8. **Modal — Resolve** — type a resolution note ("Pipe repaired. Road cleared.")
   and click Mark as Resolved.
9. **History** — scroll to Status History in the modal to see every transition.
10. **Reopen** — click the resolved report again, type a reopen reason, submit.
    Status stays "resolved"; reopen_reason is stored for admin review.

---

## Limitations

| Limitation | Detail |
|------------|--------|
| No authentication | Dashboard is open. Add auth before any production use. |
| Map needs internet | Leaflet tiles are fetched from openstreetmap.org. Core list works offline. |
| Priority is a prototype | Keyword-based only. No external data consulted. |
| Classifier is rule-based | Not ML. Not AI image recognition. |
| SQLite only | Suitable for demo. Set `DATABASE_URL` for PostgreSQL in production. |
| No notifications | No email or push notifications on status change. |
| No user accounts | Reports are not linked to any citizen identity. |

---

## Configuration (.env)

Copy `.env.example` to `.env` and edit as needed:

```env
DATABASE_URL=sqlite:///./civiclens.db
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_MB=5
API_VERSION=1.0.0
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Port 8000 already in use` | Kill the old process: `Stop-Process -Name python` |
| `Map tiles not loading` | Internet required for tiles. Reports list still works. |
| `400 / 500 on submit` | Check that backend is running on port 8000. |
| `New columns missing` | Auto-migration runs on startup. Delete `civiclens.db` to start fresh. |
| `seed_data.py fails` | Run with `.venv\Scripts\python seed_data.py` not bare `python`. |

---

## 2-Minute Hackathon Presentation Script

> "CivicLens AI is a civic issue reporting platform. Citizens use the mobile-friendly
> form to report potholes, burst pipes, broken streetlights, or garbage. They provide
> a description, optional photo, and their GPS location — no account needed.
>
> When a report is submitted, a rule-based classifier suggests the category and an
> explainable priority score is calculated from keyword density, category severity,
> and location. Every factor is listed transparently in the dashboard — we make no
> claim of AI or external data.
>
> On the admin dashboard, which is clearly labelled as a demo with no authentication,
> we see live statistics from the SQLite database, a Leaflet map with colour-coded
> markers, and a filterable report list. Clicking any report shows the full detail
> modal: priority breakdown, nearby duplicate warnings using the Haversine formula,
> workflow buttons, and a resolution form where an admin can add a resolution note
> and optional after-photo.
>
> If a resolved issue reappears, a citizen can submit a reopen request with a reason.
> The reason is stored for admin review — we never auto-reopen or auto-merge records.
>
> The test suite has 154 automated tests, all passing. Browser automation is not
> available in this environment, so we verified with HTTP smoke tests against the
> live server instead."
