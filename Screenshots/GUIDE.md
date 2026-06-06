# Screenshot Guide — Northwind Expense Review

This folder holds all UI screenshots referenced in the root README.md.  
Below is what each screenshot should capture and how to take it perfectly.

---

## 01_submissions_list.png

**What it shows:** The main submissions landing page with the employee/status filter sidebar and a list of submissions showing mixed statuses (Pending, Compliant, Flagged, Rejected).

**How to take it:**
- Open `http://localhost:8000`
- Make sure at least 3–4 submissions are visible with different statuses
- Leave the filter sidebar visible (do not collapse it)
- Recommended browser width: 1280px, zoom: 90%

**What the reviewer learns:** First impression of the system — how submissions are organized and how quickly a finance manager can filter to only the items that need their attention.

---

## 02_submission_detail_mixed.png

**What it shows:** The detail view for **James Walker's Austin trip** — two line items visible in the same table: Torchy's Tacos (Compliant, green, 100%) and Franklin Barbecue (Rejected, red, 100%).

**How to take it:**
- On the Submissions list, click into **James Walker → Austin carrier research**
- Scroll so both line items are fully visible in the table
- Make sure the confidence bars are rendered
- Do NOT open any modal — the table view is the shot

**What the reviewer learns:** The color-coded verdict table is the fastest way for a human reviewer to triage a submission — one glance shows what's clean and what needs attention.

---

## 03_alcohol_rejection_detail.png

**What it shows:** The line item detail modal for Franklin Barbecue — Rejected verdict at 100% confidence, with three verbatim policy citations (TEP-002 §6, TEP-003 §3.1, TEP-003 §7.1) shown as blockquotes.

**How to take it:**
- On the Austin submission, click **Details** on the Franklin Barbecue row
- Wait for the modal to fully load
- **Scroll inside the modal** until all three policy citation blockquotes are visible
- Make the browser window wide enough that the modal is not clipped (1280px recommended)

**What the reviewer learns:** This is the single most important screenshot — it shows that the AI cites real, verbatim policy text rather than fabricating rules. The blockquoted excerpts prove the verdict is grounded in the actual policy library.

---

## 04_over_cap_rejection.png

**What it shows:** The line item detail modal for Priya Patel's Alinea dinner — Rejected at 95% confidence because $148.20 exceeds the $75 per-person solo dinner cap (TEP-002 §2).

**How to take it:**
- Open the submission for **Priya Patel → Chicago vendor visit**
- Click **Details** on the Alinea line item
- Capture the modal showing the verdict, reasoning, and TEP-002 citation with the dollar cap quoted

**What the reviewer learns:** The system handles a different rejection type (dollar amount violation) with the same precision as the alcohol case. It also demonstrates context awareness — the same restaurant would be compliant if clients were present, because the client entertainment cap is $150.

---

## 05_compliant_item.png

**What it shows:** The line item detail modal for Torchy's Tacos — Compliant at 100% confidence, reasoning confirms $18.40 is within the $35 solo lunch cap, no flags.

**How to take it:**
- Still on the Austin submission (or any clean submission)
- Click **Details** on the Torchy's Tacos row
- Capture the full modal — the green Compliant badge and clean reasoning are the key visual

**What the reviewer learns:** The system is not a rejection machine. Straightforward, in-policy expenses are cleared quickly and cleanly, so reviewers can focus their time on genuine issues.

---

## 06_qa_answer_with_citation.png

**What it shows:** The Policy Q&A tab answering a question about dinner caps, with a verbatim TEP-002 blockquote in the response.

**How to take it:**
- Click the **Policy Q&A** tab
- Type: `What is the per-person dinner cap for solo travel, and how does it change in Tier 1 cities?`
- Wait for the full response to load
- Capture the question input, the answer text, and the citation blockquote all in one screenshot

**What the reviewer learns:** The Q&A feature gives reviewers an instant, cited reference for any policy question without digging through PDFs. Every answer is grounded — if the policy doesn't cover it, the system says so.

---

## 07_qa_refusal.png

**What it shows:** The Policy Q&A tab refusing an out-of-scope question ("Who built the Eiffel Tower?") with a clear explanation.

**How to take it:**
- In the Policy Q&A tab, type: `Who built the Eiffel Tower?`
- Wait for the refusal response
- Capture the refusal message — it should explain the question is outside the policy library scope

**Bonus shot:** Also try `What is our vacation policy?` — this should also be refused since vacation/leave is not in the T&E policy library. Shows the refusal is semantically aware, not just keyword-blocking.

**What the reviewer learns:** The system knows what it doesn't know. A Q&A tool that makes up answers is worse than no tool at all — this screenshot demonstrates the hard refusal that protects reviewer trust.

---

## Tips for all screenshots

| Setting | Value |
|---|---|
| Browser zoom | 90% |
| Window width | 1280px minimum |
| Capture tool (Windows) | `Win + Shift + S` → region select |
| File format | PNG (not JPEG — avoids compression artifacts on text) |
| Modal screenshots | Make sure no scrollbar cuts off the citation blockquotes |

Once screenshots are taken, drop the PNG files into this folder using the exact filenames above. The root `README.md` already references them and will display them automatically on GitHub.
