"""
smoke_test.py — Quick live endpoint verification against running server.
Run with: python smoke_test.py
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8000"
PASS = []
FAIL = []


def check(label, condition, detail=""):
    if condition:
        PASS.append(label)
        print(f"  [PASS] {label}")
    else:
        FAIL.append(label)
        print(f"  [FAIL] {label} — {detail}")


def get(path):
    r = urllib.request.urlopen(BASE + path)
    return r.status, json.loads(r.read())


def post_form(path, fields: dict):
    boundary = "CivicLensBoundary"
    parts = []
    for k, v in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{k}\"\r\n\r\n"
            f"{v}\r\n"
        )
    parts.append(f"--{boundary}--\r\n")
    body = "".join(parts).encode()
    req = urllib.request.Request(
        BASE + path, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    r = urllib.request.urlopen(req)
    return r.status, json.loads(r.read())


print("\n=== CivicLens AI — Live Smoke Test ===\n")

# 1. Health
print("[1] GET /health")
status, data = get("/health")
check("status 200", status == 200)
check("body.status == ok", data.get("status") == "ok")
check("body.database == ok", data.get("database") == "ok")

# 2. POST /reports
print("\n[2] POST /reports")
status, data = post_form("/reports", {
    "category": "water_leak",
    "description": "Burst pipe flooding the pavement outside 42 Elm Street urgently",
    "latitude": "51.5074",
    "longitude": "-0.1278",
})
check("status 201", status == 201)
check("has id", "id" in data and data["id"] > 0)
check("status == submitted", data.get("status") == "submitted")
check("has classifier", "classifier" in data)
check("priority 0-100", 0 <= data.get("priority_score", -1) <= 100)
report_id = data.get("id")

# 3. GET /reports
print("\n[3] GET /reports")
status, data = get("/reports")
check("status 200", status == 200)
check("has total", "total" in data and data["total"] >= 1)
check("has reports list", isinstance(data.get("reports"), list))

# 4. GET /reports/{id}
print(f"\n[4] GET /reports/{report_id}")
status, data = get(f"/reports/{report_id}")
check("status 200", status == 200)
check("correct id", data.get("id") == report_id)
check("correct category", data.get("category") == "water_leak")
check("has created_at", "created_at" in data)

# 5. GET /reports/{invalid_id}
print("\n[5] GET /reports/999999 (expect 404)")
try:
    urllib.request.urlopen(BASE + "/reports/999999")
    check("returns 404", False, "Expected 404 but got 200")
except urllib.error.HTTPError as e:
    check("returns 404", e.code == 404)

print(f"\n=== Results: {len(PASS)} passed, {len(FAIL)} failed ===\n")
sys.exit(0 if not FAIL else 1)
