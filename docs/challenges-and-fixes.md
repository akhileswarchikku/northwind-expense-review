# Implementation Challenges and Fixes

Real problems encountered during development, what caused them, and exactly how each was resolved.

---

## Challenge 1 — Policy Q&A Refusing Every Question

**Symptom:** Every Q&A question returned a refusal, even clearly in-scope policy questions like *"What is the dinner cap?"*

**Root cause:** A scale mismatch between the retrieval confidence threshold and the actual score range.

The threshold `RETRIEVAL_MIN_CONFIDENCE = 0.18` was set assuming retrieval scores are cosine similarities in [0, 1]. But the retrieval service uses Reciprocal Rank Fusion (RRF), which produces raw scores in the range **[0, ~0.033]** — not [0, 1]. Every query was returning a max score of ~0.03, which fell far below the 0.18 threshold, so the system refused every question regardless of how relevant the retrieved chunks were.

**Fix:** Normalize RRF scores to [0, 1] by dividing by the theoretical maximum. When a chunk ranks #1 in both the dense and sparse indices, the maximum possible RRF score is `1/(k+0) + 1/(k+0) = 2/k`. With k=60, that's `2/60 ≈ 0.0333`.

```python
# Before fix — raw RRF scores in [0, 0.033]
norm_score = rrf[cid]

# After fix — normalized to [0, 1]
theoretical_max = 2.0 / k   # k=60
norm_score = min(1.0, rrf[cid] / theoretical_max)
```

After this fix all 6/6 Q&A smoke test cases passed. The threshold `0.18` now means "the top chunk scores at least 18% of the maximum possible retrieval confidence", which is a meaningful and correctly calibrated signal.

---

## Challenge 2 — OpenRouter 404: Model Not Found

**Symptom:** Every LLM call returned HTTP 404 with message `"model not found"`.

**Root cause:** The original `.env` specified `google/gemini-2.0-flash-001` as both the extraction and reasoning model. This model was removed from OpenRouter between the time the brief was written and when the system was built.

**Fix:** Queried the OpenRouter models API to find the current available Gemini model:

```bash
curl https://openrouter.ai/api/v1/models | python -m json.tool | grep gemini
```

Found `google/gemini-2.5-flash` as the direct replacement — same vision capability, same JSON-mode support, lower cost. Updated `.env`:

```
EXTRACTION_MODEL=google/gemini-2.5-flash
REASONING_MODEL=google/gemini-2.5-flash
```

No code changes required — the model slug is read from config at runtime.

---

## Challenge 3 — SQLite Schema Mismatch: `no such column: employees.title`

**Symptom:** Server startup failed with `OperationalError: no such column: employees.title`.

**Root cause:** An existing `northwind.db` from an earlier version of the schema was present on disk. SQLAlchemy's `create_all()` does not alter existing tables — it only creates tables that don't exist yet. The `employees` table existed but was missing the `title` column added in a later schema revision.

**Fix:** Deleted the stale database file. SQLAlchemy recreated it with the correct schema on next startup.

```powershell
Remove-Item data\northwind.db
```

**Lesson applied:** `startup.py` now logs the schema version on startup. For a production system, Alembic migrations would handle this gracefully without requiring a data wipe.

---

## Challenge 4 — PyMuPDF Dependency Error

**Symptom:** `pip install pymupdf` failed with a dependency conflict in the Anaconda `LLM` environment.

**Root cause:** PyMuPDF's compiled binaries conflicted with existing packages in the conda environment.

**Fix:** Replaced PyMuPDF with `pdfplumber` for all PDF text extraction. `pdfplumber` is pure Python, installs without conflicts, and handles the same text extraction use case. The only limitation is that `pdfplumber` does not render PDF pages as images — but image rendering was already handled by the vision LLM fallback path, so this was not a gap.

---

## Challenge 5 — Port 8000 Already in Use

**Symptom:** `uvicorn` failed to start with `OSError: [WinError 10048] Only one usage of each socket address`.

**Root cause:** A previous server process started during testing was still bound to port 8000 after its terminal was closed.

**Fix:**

```powershell
# Find and kill the process holding port 8000
Get-NetTCPConnection -LocalPort 8000 | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }
```

---

## Challenge 6 — `charset-normalizer` Version Conflict

**Symptom:** `pdfplumber` raised an import error about `charset-normalizer` version incompatibility.

**Root cause:** `pdfminer.six` (a `pdfplumber` dependency) required `charset-normalizer>=3.4.5`, but the conda environment had `3.4.4` installed.

**Fix:**

```bash
conda run -n LLM pip install --upgrade charset-normalizer
```

This upgraded `charset-normalizer` from 3.4.4 to 3.4.5 without breaking any other packages.

---

## Challenge 7 — Conda Run with Multi-line Scripts

**Symptom:** `conda run -n LLM python -c "..."` failed when the `-c` argument contained newlines.

**Root cause:** `conda run` passes the command argument as a shell string. PowerShell strips newlines before passing it, which caused syntax errors in the embedded Python code.

**Fix:** Write multi-line Python to a temporary `.py` file and run that file instead of using `-c`:

```powershell
# Instead of this (breaks with newlines):
conda run -n LLM python -c "
import json
...
"

# Do this:
Set-Content -Path tmp_script.py -Value "import json`n..."
conda run -n LLM python tmp_script.py
Remove-Item tmp_script.py
```
