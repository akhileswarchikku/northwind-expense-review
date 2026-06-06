"""
Extract structured data from receipts in PDF, image, or plain-text format.
Falls back to vision LLM for images and scanned PDFs.
"""
import json
import logging
from pathlib import Path

import pdfplumber

from backend.services import llm_client
from backend import config

log = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
_TEXT_EXTS  = {".txt", ".csv", ".tsv"}
_PDF_EXTS   = {".pdf"}

EXTRACTION_PROMPT = """You are an expense receipt data extractor for Northwind Logistics.
Extract structured data from this receipt text and return a JSON object with exactly these keys:

{
  "vendor": "merchant name (string)",
  "date": "YYYY-MM-DD (string, best estimate if partial)",
  "amount": total amount as a number (float),
  "currency": "3-letter code, default USD",
  "category": one of ["flights", "lodging", "meals", "ground_transport", "conference", "other"],
  "description": "brief description of what was purchased",
  "party_size": number of people if discernible (integer or null),
  "alcohol_present": true if any alcoholic beverage appears on the receipt (boolean),
  "line_items": [{"description": "...", "amount": 0.00}] array of individual line items if visible,
  "notes": "any flags or observations (e.g., alcohol charges, unusual items)"
}

Rules:
- amount is the final total the employee paid (after tax, tip)
- If a field cannot be determined from the text, use null
- For category: flights=air travel, lodging=hotel/Airbnb, meals=food/dining, ground_transport=Uber/Lyft/taxi/train, conference=registration/event fees
- Set alcohol_present=true if ANY alcoholic beverages appear on the receipt

Receipt text:
"""

VISION_EXTRACTION_PROMPT = EXTRACTION_PROMPT + "\n[Image attached — extract from the visual receipt above]"


def _detect_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _PDF_EXTS:
        return "pdf"
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _TEXT_EXTS:
        return "text"
    return "unknown"


def _extract_pdf_text(path: Path) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            t = pg.extract_text()
            if t:
                pages.append(t)
    return "\n\n".join(pages)


async def extract_receipt(path: Path) -> dict:
    """
    Extract structured data from a receipt file.
    Returns a dict with vendor, date, amount, currency, category, description, etc.
    """
    file_type = _detect_type(path)
    raw_text = ""

    try:
        if file_type == "pdf":
            raw_text = _extract_pdf_text(path)
            if len(raw_text.strip()) < 30:
                # Likely scanned PDF — re-extract via vision
                log.info("PDF appears to be scanned, using vision model for %s", path.name)
                result = await llm_client.chat_vision_json(
                    prompt=VISION_EXTRACTION_PROMPT,
                    image_path=path,
                    model=config.EXTRACTION_MODEL,
                )
                result["file_type"] = "pdf"
                result["raw_text"] = raw_text
                return result

        elif file_type == "image":
            log.info("Using vision model for image receipt %s", path.name)
            result = await llm_client.chat_vision_json(
                prompt=VISION_EXTRACTION_PROMPT,
                image_path=path,
                model=config.EXTRACTION_MODEL,
            )
            result["file_type"] = "image"
            result["raw_text"] = ""
            return result

        else:  # text or unknown
            raw_text = path.read_text(encoding="utf-8", errors="replace")

        # Text-based extraction via chat
        messages = [
            {
                "role": "system",
                "content": "You are a receipt parser. Return only valid JSON, no extra text.",
            },
            {
                "role": "user",
                "content": EXTRACTION_PROMPT + raw_text,
            },
        ]
        result = await llm_client.chat_json(
            messages=messages,
            model=config.EXTRACTION_MODEL,
        )
        result["file_type"] = file_type
        result["raw_text"] = raw_text
        return result

    except Exception as exc:
        log.error("Extraction failed for %s: %s", path.name, exc)
        return {
            "vendor": None,
            "date": None,
            "amount": None,
            "currency": "USD",
            "category": "other",
            "description": f"Extraction failed: {exc}",
            "party_size": None,
            "alcohol_present": False,
            "line_items": [],
            "notes": str(exc),
            "file_type": file_type,
            "raw_text": raw_text,
        }
