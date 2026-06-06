"""Smoke test — run while server is up on port 8000."""
import httpx, json, sys

BASE = "http://localhost:8000"

def check(label, condition, detail=""):
    mark = "✓" if condition else "✗"
    print(f"  {mark}  {label}" + (f" — {detail}" if detail else ""))
    return condition

results = []

# 1. Employees seeded
r = httpx.get(f"{BASE}/api/employees")
results.append(check("Employees seeded", r.status_code == 200 and len(r.json()) >= 5, f"{len(r.json())} found"))

# 2. Policy index
r = httpx.get(f"{BASE}/api/policy/index/status")
d = r.json()
results.append(check("Policy index built", d["indexed"] and d["chunk_count"] >= 80, f"{d['chunk_count']} chunks"))

# 3. Create submission
r = httpx.post(f"{BASE}/api/submissions", json={"employee_id": "NW-03488", "trip_purpose": "Smoke test", "trip_dates_start": "2025-03-18", "trip_dates_end": "2025-03-20"})
results.append(check("Create submission", r.status_code == 201))
sub_id = r.json()["id"]

# 4. Upload receipt
with open(r"data\submissions\04_alcohol_solo_travel\receipts\05_dinner_franklin.pdf", "rb") as f:
    r = httpx.post(f"{BASE}/api/submissions/{sub_id}/receipts", files=[("files", ("05_dinner_franklin.pdf", f, "application/pdf"))], timeout=120)
results.append(check("Upload + review receipt", r.status_code == 200))
li = r.json()["line_items"][0]
results.append(check("Alcohol correctly rejected", li["verdict"] == "rejected", f"verdict={li['verdict']} conf={li['confidence']:.2f}"))
cits = json.loads(li.get("policy_citations") or "[]")
results.append(check("TEP-003 cited", any(c.get("doc_id") == "TEP-003" for c in cits), f"citations={[c.get('doc_id') for c in cits]}"))

# 5. Q&A answers
r = httpx.post(f"{BASE}/api/policy/qa", json={"question": "What is the dinner cap for solo travel?"}, timeout=60)
d = r.json()
results.append(check("Q&A answers policy question", not d["refused"] and "75" in d.get("answer",""), f"answer='{d.get('answer','')[:60]}'"))

r = httpx.post(f"{BASE}/api/policy/qa", json={"question": "Who built the Eiffel Tower?"}, timeout=60)
d = r.json()
results.append(check("Q&A refuses out-of-scope", d["refused"]))

# Summary
passed = sum(results)
total = len(results)
print(f"\n  {passed}/{total} checks passed")
sys.exit(0 if passed == total else 1)
