"""live_check.py — Phase 3 live endpoint verification."""
import urllib.request, urllib.parse, json, sys, io

B = "http://localhost:8000"
PASS, FAIL = [], []

def get(path):
    r = urllib.request.urlopen(B + path)
    return r.status, json.loads(r.read())

def post_json(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(B + path, data=data,
          headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req)
    return r.status, json.loads(r.read())

def post_form(path, fields):
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    body_parts = []
    for k, v in fields.items():
        body_parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
        )
    body_parts.append(f'--{boundary}--\r\n')
    body = "".join(body_parts).encode()
    req = urllib.request.Request(B + path, data=body,
          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
          method="POST")
    r = urllib.request.urlopen(req)
    return r.status, json.loads(r.read())

def patch_json(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(B + path, data=data,
          headers={"Content-Type": "application/json"}, method="PATCH")
    r = urllib.request.urlopen(req)
    return r.status, json.loads(r.read())

def check(label, ok, note=""):
    if ok:
        PASS.append(label)
        print(f"  [PASS] {label}" + (f" — {note}" if note else ""))
    else:
        FAIL.append(label)
        print(f"  [FAIL] {label}" + (f" — {note}" if note else ""))

print("\n=== CivicLens AI — Final Live Endpoint Check ===\n")

# Health
s, d = get("/health")
check("GET /health", s == 200)
check("health.database ok", d.get("database") == "ok")

# Stats
s, d = get("/stats")
check("GET /stats", s == 200)
check("stats.total_reports >= 9", d.get("total_reports", 0) >= 9,
      f"got {d.get('total_reports')}")
check("stats.by_category has pothole", "pothole" in d.get("by_category", {}))

# Map data
s, d = get("/map-data")
check("GET /map-data", s == 200)
check("map has features", d.get("total_with_coordinates", 0) >= 1)

# Reports list + filters
s, d = get("/reports?limit=5")
check("GET /reports", s == 200)
check("reports.total >= 9", d.get("total", 0) >= 9)
s, d = get("/reports?category=pothole")
check("GET /reports?category=pothole", s == 200)
check("pothole filter works", all(r["category"] == "pothole" for r in d["reports"]))

# Submit a citizen report (full workflow)
s, d = post_form("/reports", {
    "category": "water_leak",
    "description": "Test pipe burst flooding pavement outside school gate entrance",
})
check("POST /reports (citizen submit)", s == 201)
rid = d.get("id")
check("response has id", rid is not None)
check("response has classifier", "classifier" in d)
check("response has priority_breakdown", "priority_breakdown" in d)
check("status is submitted", d.get("status") == "submitted")

# Retrieve the report
s, d = get(f"/reports/{rid}")
check(f"GET /reports/{rid}", s == 200)
check("resolution_note field present", "resolution_note" in d)
check("reopen_reason field present", "reopen_reason" in d)

# Duplicates + priority + history
s, d = get(f"/reports/{rid}/duplicates")
check(f"GET /reports/{rid}/duplicates", s == 200)
s, d = get(f"/reports/{rid}/priority")
check(f"GET /reports/{rid}/priority", s == 200)
check("priority score in range", 0 <= d.get("priority_score", -1) <= 100)
check("priority breakdown has factors", len(d.get("breakdown", {}).get("factors", [])) >= 1)
check("disclaimer present", len(d.get("breakdown", {}).get("disclaimer", "")) > 20)

# Advance status: submitted → assigned → in_progress
s, d = patch_json(f"/reports/{rid}/status", {"status": "assigned"})
check("PATCH status → assigned", s == 200)
s, d = patch_json(f"/reports/{rid}/status", {"status": "in_progress"})
check("PATCH status → in_progress", s == 200)

# Resolve
s, d = post_form(f"/reports/{rid}/resolve",
    {"resolution_note": "Water main repaired. Road surface restored to full condition."})
check("POST /resolve", s == 200)
check("resolve returns status=resolved", d.get("status") == "resolved")
check("resolve returns note", d.get("resolution_note") is not None)

# Verify resolved in GET
s, d = get(f"/reports/{rid}")
check("resolved_at set in DB", d.get("resolved_at") is not None)
check("resolution_note in GET response", d.get("resolution_note") is not None)

# Reopen
s, d = post_json(f"/reports/{rid}/reopen",
    {"reason": "The water leak has reappeared after heavy rainfall over the past few days."})
check("POST /reopen", s == 200)
check("reopen keeps status resolved", d.get("status") == "resolved")
check("reopen_reason returned", d.get("reopen_reason") is not None)

# History
s, d = get(f"/reports/{rid}/history")
check("GET /history", s == 200)
check("history has >=3 entries", len(d.get("history", [])) >= 3)

# Error cases
try:
    urllib.request.urlopen(B + "/reports/999999")
    check("404 for nonexistent report", False, "expected 404")
except urllib.error.HTTPError as e:
    check("404 for nonexistent report", e.code == 404)

# Seed idempotency
import subprocess, sys as _sys
result = subprocess.run(
    [".venv/Scripts/python", "seed_data.py", "--dry-run"],
    capture_output=True, text=True, cwd="."
)
check("seed_data.py --dry-run exits 0", result.returncode == 0)

print(f"\n=== Results: {len(PASS)} passed, {len(FAIL)} failed ===\n")
if FAIL:
    print("FAILED checks:")
    for f in FAIL:
        print(f"  - {f}")
sys.exit(0 if not FAIL else 1)
