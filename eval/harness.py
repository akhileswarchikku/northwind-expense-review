#!/usr/bin/env python3
"""
Northwind Expense Review — Evaluation Harness

Usage:
    python eval/harness.py --api http://localhost:8000 --test-cases eval/test_cases.json

Input format (test_cases.json):
{
  "test_cases": [
    {
      "id": "tc_001",
      "employee": {
        "id": "NW-XXXXX",   # existing employee ID, or full dict to create
        ...
      },
      "trip": {
        "purpose": "...",
        "start": "YYYY-MM-DD",
        "end": "YYYY-MM-DD"
      },
      "receipts": [
        {
          "filename": "receipt.pdf",   # relative path from test-cases file dir
          "expected_verdict": "compliant" | "flagged" | "rejected",
          "expected_category": "meals" | "flights" | "lodging" | "ground_transport" | "conference" | "other",
          "expected_citation_doc": "TEP-003",  # optional: at least one citation must reference this doc
          "notes": "free text"
        }
      ],
      "qa_tests": [
        {
          "question": "...",
          "should_refuse": true | false,
          "should_cite": "TEP-002"   # optional
        }
      ]
    }
  ]
}

Output metrics:
  - verdict_accuracy:    % of line items where actual verdict == expected_verdict
  - category_accuracy:   % of line items where actual category == expected_category
  - citation_hit_rate:   % of items with expected_citation_doc where it appears in citations
  - refusal_accuracy:    % of QA tests where refused matches should_refuse
  - mean_confidence:     mean confidence score across all verdicts
  - low_confidence_rate: % of verdicts with confidence < 0.4
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# ── helpers ───────────────────────────────────────────────────────────────────

def api_get(base: str, path: str) -> dict:
    r = httpx.get(base + path, timeout=60)
    r.raise_for_status()
    return r.json()


def api_post(base: str, path: str, body: dict) -> dict:
    r = httpx.post(base + path, json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def api_post_files(base: str, path: str, files: list[Path]) -> dict:
    fd = [("files", (f.name, f.read_bytes(), _mime(f))) for f in files]
    r = httpx.post(base + path, files=fd, timeout=300)
    r.raise_for_status()
    return r.json()


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".txt": "text/plain"}.get(ext, "application/octet-stream")


def ensure_employee(base: str, emp_spec: dict) -> str:
    """Return employee ID, creating if needed."""
    emp_id = emp_spec.get("id") or emp_spec.get("employee_id")
    try:
        api_get(base, f"/api/employees/{emp_id}")
        return emp_id
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            payload = {
                "id": emp_id,
                "name": emp_spec.get("name", "Test Employee"),
                "grade": emp_spec.get("grade", 5),
                "title": emp_spec.get("title", ""),
                "department": emp_spec.get("department", ""),
                "home_base": emp_spec.get("home_base", ""),
            }
            api_post(base, "/api/employees", payload)
            return emp_id
        raise


# ── metrics ───────────────────────────────────────────────────────────────────

class Metrics:
    def __init__(self):
        self.verdict_total = 0
        self.verdict_correct = 0
        self.category_total = 0
        self.category_correct = 0
        self.citation_total = 0
        self.citation_hits = 0
        self.qa_total = 0
        self.qa_refusal_correct = 0
        self.confidences: list[float] = []
        self.failures: list[dict] = []

    def record_verdict(self, expected: str, actual: str, confidence: float, item_id: str, notes: str = ""):
        self.verdict_total += 1
        ok = expected == actual
        self.verdict_correct += ok
        if confidence is not None:
            self.confidences.append(confidence)
        if not ok:
            self.failures.append({"type": "verdict", "item": item_id,
                                  "expected": expected, "actual": actual,
                                  "confidence": confidence, "notes": notes})

    def record_category(self, expected: str, actual: str, item_id: str):
        if not expected:
            return
        self.category_total += 1
        ok = expected == actual
        self.category_correct += ok
        if not ok:
            self.failures.append({"type": "category", "item": item_id,
                                  "expected": expected, "actual": actual})

    def record_citation(self, expected_doc: str, citations: list, item_id: str):
        if not expected_doc:
            return
        self.citation_total += 1
        doc_ids = {c.get("doc_id", "") for c in citations}
        hit = expected_doc in doc_ids
        self.citation_hits += hit
        if not hit:
            self.failures.append({"type": "citation", "item": item_id,
                                  "expected_doc": expected_doc, "found_docs": list(doc_ids)})

    def record_qa(self, should_refuse: bool, refused: bool, question: str):
        self.qa_total += 1
        ok = should_refuse == refused
        self.qa_refusal_correct += ok
        if not ok:
            self.failures.append({"type": "qa_refusal", "question": question,
                                  "expected_refuse": should_refuse, "actual_refuse": refused})

    def report(self) -> dict:
        def pct(a, b):
            return round(a / b * 100, 1) if b else None

        mean_conf = round(sum(self.confidences) / len(self.confidences), 3) if self.confidences else None
        low_conf_rate = pct(sum(1 for c in self.confidences if c < 0.4), len(self.confidences))

        return {
            "verdict_accuracy":    pct(self.verdict_correct, self.verdict_total),
            "category_accuracy":   pct(self.category_correct, self.category_total),
            "citation_hit_rate":   pct(self.citation_hits, self.citation_total),
            "refusal_accuracy":    pct(self.qa_refusal_correct, self.qa_total),
            "mean_confidence":     mean_conf,
            "low_confidence_rate": low_conf_rate,
            "counts": {
                "verdicts_tested":  self.verdict_total,
                "categories_tested": self.category_total,
                "citations_tested":  self.citation_total,
                "qa_tested":         self.qa_total,
            },
            "failures": self.failures,
        }


# ── main ──────────────────────────────────────────────────────────────────────

def run(api_base: str, test_cases_path: Path) -> dict:
    test_data = json.loads(test_cases_path.read_text())
    cases = test_data.get("test_cases", [])
    base_dir = test_cases_path.parent
    metrics = Metrics()

    for tc in cases:
        tc_id = tc.get("id", "?")
        print(f"\n── Test case: {tc_id} ──")

        # 1. Ensure employee exists
        emp_id = ensure_employee(api_base, tc["employee"])

        # 2. Create submission
        trip = tc.get("trip", {})
        sub = api_post(api_base, "/api/submissions", {
            "employee_id": emp_id,
            "trip_purpose": trip.get("purpose", "Test trip"),
            "trip_dates_start": trip.get("start", "2025-01-01"),
            "trip_dates_end": trip.get("end", "2025-01-03"),
        })
        sub_id = sub["id"]
        print(f"  Created submission {sub_id}")

        # 3. Upload receipts
        receipt_specs = tc.get("receipts", [])
        if receipt_specs:
            receipt_paths = []
            for rs in receipt_specs:
                rp = base_dir / rs["filename"]
                if rp.exists():
                    receipt_paths.append(rp)
                else:
                    print(f"  WARNING: receipt not found: {rp}")

            if receipt_paths:
                print(f"  Uploading {len(receipt_paths)} receipt(s)…")
                sub = api_post_files(api_base, f"/api/submissions/{sub_id}/receipts", receipt_paths)
                time.sleep(1)

        # 4. Evaluate line items
        sub = api_get(api_base, f"/api/submissions/{sub_id}")
        items = sub.get("line_items", [])

        # Match items to specs by filename (case-insensitive)
        item_map = {li["filename"].lower(): li for li in items}
        for rs in receipt_specs:
            fname = Path(rs["filename"]).name.lower()
            li = item_map.get(fname)
            if not li:
                print(f"  WARN: no line item found for {fname}")
                continue

            citations = json.loads(li.get("policy_citations") or "[]")
            exp_verdict   = rs.get("expected_verdict")
            exp_category  = rs.get("expected_category")
            exp_cite_doc  = rs.get("expected_citation_doc")

            if exp_verdict:
                metrics.record_verdict(
                    expected=exp_verdict,
                    actual=li.get("verdict"),
                    confidence=li.get("confidence"),
                    item_id=li["id"],
                    notes=rs.get("notes", ""),
                )
                status_mark = "✓" if li.get("verdict") == exp_verdict else "✗"
                print(f"  {status_mark} {fname}: expected={exp_verdict}, actual={li.get('verdict')}, conf={li.get('confidence'):.2f}")

            if exp_category:
                metrics.record_category(exp_category, li.get("category"), li["id"])

            if exp_cite_doc:
                metrics.record_citation(exp_cite_doc, citations, li["id"])

        # 5. Evaluate Q&A tests
        for qa in tc.get("qa_tests", []):
            question = qa["question"]
            should_refuse = qa.get("should_refuse", False)
            resp = api_post(api_base, "/api/policy/qa", {"question": question})
            actual_refused = resp.get("refused", False)
            metrics.record_qa(should_refuse, actual_refused, question)
            mark = "✓" if should_refuse == actual_refused else "✗"
            print(f"  {mark} QA: '{question[:60]}…' — refused={actual_refused}")

    return metrics.report()


def main():
    parser = argparse.ArgumentParser(description="Northwind Eval Harness")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--test-cases", required=True, help="Path to test_cases.json")
    parser.add_argument("--out", default=None, help="Write JSON results to file")
    args = parser.parse_args()

    results = run(args.api, Path(args.test_cases))
    print("\n" + "="*50)
    print("EVALUATION RESULTS")
    print("="*50)
    for k, v in results.items():
        if k != "failures":
            print(f"  {k}: {v}")
    if results.get("failures"):
        print(f"\n  Failures ({len(results['failures'])}):")
        for f in results["failures"][:10]:
            print(f"    {f}")

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))
        print(f"\nResults written to {args.out}")

    # Exit non-zero if any accuracy metric is below 50%
    accs = [v for k, v in results.items() if "accuracy" in k and v is not None]
    sys.exit(0 if all(a >= 50 for a in accs) else 1)


if __name__ == "__main__":
    main()
