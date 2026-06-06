# Prompt Engineering

How the LLM prompts are structured, why certain design choices were made, and how hallucinations are prevented.

---

## Overview

The system uses three distinct prompts:

| Prompt | Purpose | Output |
|---|---|---|
| Extraction | Parse raw receipt text or image into structured data | JSON with vendor, amount, category, etc. |
| Review | Evaluate one expense line item against policy | JSON with verdict, reasoning, citations, confidence |
| Q&A | Answer a free-form policy question | JSON with answer, citations, refused flag |

All three return JSON. This is enforced by:
1. Sending `"response_format": {"type": "json_object"}` in the API request
2. Including `"Return ONLY a JSON object"` in the system prompt
3. Post-processing that strips markdown fences (` ```json ` blocks) if the model wraps its output despite the instruction

---

## Extraction Prompt

The extraction prompt instructs the model to pull structured fields from raw receipt content. The schema is fixed and explicitly listed in the prompt:

```
Extract the following from this receipt and return JSON:
{
  "vendor": string,
  "date": "YYYY-MM-DD",
  "amount": float,
  "currency": "USD",
  "category": "meals" | "lodging" | "flights" | "ground_transport" | "conference" | "other",
  "description": string,
  "party_size": int or null,
  "alcohol_present": bool,
  "line_items": [{"description": string, "amount": float}],
  "notes": string or null
}
```

**Why `alcohol_present` as a boolean:** Alcohol detection is a high-stakes flag in the policy (TEP-003 prohibits it on solo travel entirely). Asking the model to return a boolean here means the reviewer system always has a pre-extracted signal to include in the retrieval query, rather than relying on the reviewer LLM to infer it from unstructured text.

**Why `party_size`:** The per-meal dollar cap in TEP-002 is per-person. A $150 dinner for two people ($75/person) is compliant; the same receipt for one person is rejected. The reviewer LLM needs party size to apply the cap correctly.

---

## Review Prompt

This is the most complex prompt in the system. The system message establishes the reviewer persona and hard rules:

```
You are a meticulous expense policy compliance reviewer at Northwind Logistics.

Approach:
1. Identify the expense category and look for the most relevant policy excerpt(s).
2. Check amounts against applicable per-person caps (considering employee grade, city tier, client vs solo).
3. Check for prohibited items (alcohol on solo travel, in-room charges, personal items, etc.).
4. Consider trip context — is the expense dated within the trip? Is it business-appropriate?
5. If evidence is mixed or retrieval confidence is low, use "flagged" rather than "rejected".
```

### Verdict definitions

Explicit definitions prevent the model from treating the three verdicts as arbitrary labels:

```
"compliant": expense clearly meets policy; no material issues
"flagged": potential violation or ambiguity requiring human judgement
"rejected": clear policy violation that should not be reimbursed
```

The key design choice: **bias toward `flagged` over `rejected` when evidence is mixed**. A false negative (human reviews a flagged item) is cheaper than a false positive (legitimate expense incorrectly rejected). This is stated explicitly in the prompt as instruction 5.

### Citation rules — preventing hallucination

The single most important anti-hallucination rule in the system:

```
Rules for citations:
- Only cite from the POLICY EXCERPTS provided — do NOT invent doc IDs or quotes.
- If no excerpts are relevant, say so in reasoning and set policy_citations to [].
- Quotes must be verbatim from the excerpts (partial is fine; keep them under 200 chars).
```

This works because:
1. The retrieved policy chunks are the *only* policy text the model ever sees
2. The prompt explicitly prohibits citing anything not in those excerpts
3. Verbatim quotes are checkable — a reviewer can ctrl-F the source PDF to verify

### Confidence calibration

The prompt provides numeric guidance for what each confidence range means:

```
0.9–1.0: clear rule in excerpts, unambiguous facts
0.6–0.9: rule present but interpretation requires judgement
0.3–0.6: relevant excerpts weak or missing; verdict uncertain
< 0.3:   almost no relevant policy found
```

Without this guidance, models tend to produce clustered high-confidence scores (0.8–1.0 for everything) which provides no differentiation for reviewers.

### User message structure

The user message for each review is templated with four sections:

```
EMPLOYEE:          ← grade, department, home base
TRIP CONTEXT:      ← purpose, start date, end date
EXPENSE LINE ITEM: ← vendor, amount, category, alcohol_present, party_size, etc.
POLICY EXCERPTS:   ← 6 retrieved chunks, numbered [1]–[6] with doc_id and section header
```

Ordering matters: employee context and trip context come before the expense so the model builds a mental model of the situation before seeing the amount. This reduces the chance of the model anchoring on the dollar figure without considering the business context.

---

## Q&A Prompt

The Q&A system prompt is shorter because the scope is more constrained:

```
Answer questions about the company's Travel & Expense and other policies using ONLY the policy excerpts provided.

Rules:
- If the excerpts do not contain enough information to answer, return refused=true and explain why.
- Do NOT answer questions unrelated to the policy library (personal advice, general knowledge, etc.).
- Cite specific clauses with verbatim quotes.
- Be concise and precise.
```

**Hard vs soft refusal:**

There are two layers of refusal:
1. **Hard refusal (no LLM call):** If retrieval confidence is below `RETRIEVAL_MIN_CONFIDENCE`, the system returns a refusal without calling the LLM at all. This is the right choice — there is no point asking the LLM to answer a question when the retrieved context has near-zero relevance.
2. **Soft refusal (LLM decides):** If retrieval found some content but it doesn't actually answer the question, the LLM is instructed to return `refused=true` with a `refusal_reason`. This handles cases where retrieval scores are acceptable but the content is coincidentally off-topic.

---

## Query Enrichment for Retrieval

Before retrieval, the reviewer builds a category-enriched query rather than just using the vendor name:

```python
parts = [f"{category} expense policy"]
if vendor:     parts.append(vendor)
if desc:       parts.append(desc)
if grade:      parts.append(f"grade {grade}")
if alcohol:    parts.append("alcohol reimbursement solo travel client entertainment")
if category == "meals":
    parts.append("per-meal cap per-person limit dinner lunch breakfast")
elif category == "lodging":
    parts.append("hotel nightly rate city tier cap")
```

**Why this matters:** A vendor name like "Franklin Barbecue" has no semantic overlap with policy text about "alcohol reimbursement" or "solo travel". The enrichment adds the right domain vocabulary so both dense and sparse retrievers can surface the relevant TEP-003 chunks. Without enrichment, the alcohol solo-travel rule often fails to appear in the top-6 retrieved chunks.
