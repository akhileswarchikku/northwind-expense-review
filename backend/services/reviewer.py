"""
Core review pipeline: given extracted receipt data + employee context,
retrieve relevant policy chunks and generate a structured verdict.
"""
import json
import logging
from typing import Optional

from backend.services import retrieval, llm_client
from backend import config

log = logging.getLogger(__name__)

REVIEW_SYSTEM = """You are a meticulous expense policy compliance reviewer at Northwind Logistics.

Your job: review a single expense line item and determine if it complies with Northwind's policy.

Approach:
1. Identify the expense category and look for the most relevant policy excerpt(s).
2. Check amounts against applicable per-person caps (considering employee grade, city tier, client vs solo).
3. Check for prohibited items (alcohol on solo travel, in-room charges, personal items, etc.).
4. Consider trip context — is the expense dated within the trip? Is it business-appropriate given the trip purpose?
5. If evidence is mixed or retrieval confidence is low, use "flagged" rather than "rejected".

Return ONLY a JSON object — no prose outside it:
{
  "verdict": "compliant" | "flagged" | "rejected",
  "reasoning": "2–4 sentence explanation for the reviewer. Be specific about which rule applies.",
  "policy_citations": [
    {
      "doc_id": "TEP-XXX",
      "section": "Section X.Y or clause description",
      "quote": "exact quoted text from the POLICY EXCERPTS below — do not fabricate",
      "relevance": "one sentence on how this clause applies to this expense"
    }
  ],
  "confidence": 0.0–1.0,
  "flags": ["specific issue 1", "specific issue 2"]
}

Rules for verdict:
- "compliant": expense clearly meets policy; no material issues
- "flagged": potential violation or ambiguity requiring human judgement (e.g., amount near cap, missing context)
- "rejected": clear policy violation that should not be reimbursed (e.g., solo alcohol, amount well over cap, prohibited item)

Rules for citations:
- Only cite from the POLICY EXCERPTS provided — do NOT invent doc IDs or quotes.
- If no excerpts are relevant, say so in reasoning and set policy_citations to [].
- Quotes must be verbatim from the excerpts (partial is fine; keep them under 200 chars).

Rules for confidence:
- 0.9–1.0: clear rule in excerpts, unambiguous facts
- 0.6–0.9: rule present but interpretation requires judgement
- 0.3–0.6: relevant excerpts weak or missing; verdict uncertain
- < 0.3: almost no relevant policy found; should trigger refusal / needs-review
"""

REVIEW_USER_TEMPLATE = """EMPLOYEE:
{employee_json}

TRIP CONTEXT:
- Purpose: {trip_purpose}
- Dates: {trip_start} to {trip_end}

EXPENSE LINE ITEM:
{item_json}

POLICY EXCERPTS (use ONLY these for citations):
{policy_excerpts}

Review the expense above and return your JSON verdict."""


QA_SYSTEM = """You are a policy expert for Northwind Logistics.
Answer questions about the company's Travel & Expense and other policies using ONLY the policy excerpts provided.

Rules:
- If the excerpts do not contain enough information to answer, return refused=true and explain why.
- Do NOT answer questions unrelated to the policy library (personal advice, general knowledge, etc.).
- Cite specific clauses with verbatim quotes.
- Be concise and precise.

Return JSON:
{
  "answer": "your answer or empty string if refused",
  "citations": [{"doc_id": "TEP-XXX", "section": "...", "quote": "..."}],
  "confidence": 0.0–1.0,
  "refused": true|false,
  "refusal_reason": "why you refused, or null if answered"
}
"""


def _format_policy_excerpts(chunks: list[dict]) -> str:
    if not chunks:
        return "(No relevant policy excerpts found.)"
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(
            f"[{i}] {c['doc_id']} — {c.get('section_header', '').strip()}\n{c['text'].strip()}"
        )
    return "\n\n---\n\n".join(parts)


def _build_review_query(item: dict, employee: dict, trip_purpose: str) -> str:
    """Build a descriptive retrieval query for this line item."""
    category = item.get("category", "expense")
    vendor = item.get("vendor", "")
    desc = item.get("description", "")
    grade = employee.get("grade", "")
    notes = item.get("notes", "")
    alcohol = item.get("alcohol_present", False)

    parts = [f"{category} expense policy"]
    if vendor:
        parts.append(vendor)
    if desc:
        parts.append(desc)
    if grade:
        parts.append(f"grade {grade}")
    if alcohol:
        parts.append("alcohol reimbursement solo travel client entertainment")
    if category == "meals":
        parts.append("per-meal cap per-person limit dinner lunch breakfast")
    elif category == "lodging":
        parts.append("hotel nightly rate city tier cap")
    elif category == "flights":
        parts.append("economy class booking air travel")
    elif category == "ground_transport":
        parts.append("ground transportation rideshare")
    elif category == "conference":
        parts.append("conference registration attendance training")

    return " ".join(parts)


async def review_line_item(
    item_data: dict,
    employee: dict,
    trip_purpose: str,
    trip_start: str,
    trip_end: str,
) -> dict:
    """
    Retrieve relevant policy chunks and generate a verdict for one expense line item.
    Returns a dict with verdict, reasoning, policy_citations, confidence, flags.
    """
    query = _build_review_query(item_data, employee, trip_purpose)
    chunks = retrieval.retrieve(query, top_k=config.RETRIEVAL_TOP_K)
    top_score = retrieval.max_score(chunks)

    policy_excerpts = _format_policy_excerpts(chunks)
    item_json = json.dumps(item_data, indent=2, default=str)
    employee_json = json.dumps(employee, indent=2, default=str)

    messages = [
        {"role": "system", "content": REVIEW_SYSTEM},
        {
            "role": "user",
            "content": REVIEW_USER_TEMPLATE.format(
                employee_json=employee_json,
                trip_purpose=trip_purpose,
                trip_start=trip_start,
                trip_end=trip_end,
                item_json=item_json,
                policy_excerpts=policy_excerpts,
            ),
        },
    ]

    try:
        result = await llm_client.chat_json(messages=messages, model=config.REASONING_MODEL)
    except Exception as exc:
        log.error("Review LLM call failed: %s", exc)
        return {
            "verdict": "flagged",
            "reasoning": f"Review pipeline error — please verify manually. Error: {exc}",
            "policy_citations": [],
            "confidence": 0.1,
            "flags": ["review_error"],
        }

    # Clamp confidence
    result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.5))))

    # If retrieval found very little (normalized score < threshold), flag uncertainty
    if top_score < config.RETRIEVAL_MIN_CONFIDENCE:
        # Soft downgrade only — don't hard-cap. The LLM has seen the excerpts and may still
        # be right. But we mark low_retrieval_confidence for the reviewer.
        adjusted = min(result["confidence"], max(0.3, top_score / config.RETRIEVAL_MIN_CONFIDENCE))
        result["confidence"] = adjusted
        if "flags" not in result:
            result["flags"] = []
        result["flags"].append("low_retrieval_confidence")

    return result


async def answer_policy_question(question: str) -> dict:
    """
    Answer a free-form question about the policy library.
    Refuses if retrieval confidence is too low.
    """
    chunks = retrieval.retrieve(question, top_k=config.RETRIEVAL_TOP_K)
    top_score = retrieval.max_score(chunks)

    # Hard refusal if no relevant content found
    if top_score < config.RETRIEVAL_MIN_CONFIDENCE:
        return {
            "answer": "",
            "citations": [],
            "confidence": top_score,
            "refused": True,
            "refusal_reason": (
                "No sufficiently relevant policy content was found to answer this question. "
                "This may be outside the scope of the Northwind policy library, or the question "
                "may need to be rephrased."
            ),
        }

    policy_excerpts = _format_policy_excerpts(chunks)
    messages = [
        {"role": "system", "content": QA_SYSTEM},
        {
            "role": "user",
            "content": f"POLICY EXCERPTS:\n{policy_excerpts}\n\nQUESTION: {question}",
        },
    ]

    try:
        result = await llm_client.chat_json(messages=messages, model=config.REASONING_MODEL)
    except Exception as exc:
        log.error("QA LLM call failed: %s", exc)
        return {
            "answer": "",
            "citations": [],
            "confidence": 0.0,
            "refused": True,
            "refusal_reason": f"System error: {exc}",
        }

    result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", top_score))))
    return result
