import base64
import json
import httpx
from pathlib import Path
from backend import config


_HEADERS = {
    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
    "HTTP-Referer": config.OPENROUTER_HTTP_REFERER,
    "X-Title": config.OPENROUTER_APP_TITLE,
    "Content-Type": "application/json",
}
_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


async def chat(
    messages: list,
    model: str | None = None,
    response_format: dict | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> str:
    model = model or config.REASONING_MODEL
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(_BASE_URL, headers=_HEADERS, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def chat_json(
    messages: list,
    model: str | None = None,
    max_tokens: int = 2048,
) -> dict:
    """Call LLM and parse the result as JSON, stripping markdown fences."""
    raw = await chat(
        messages=messages,
        model=model,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


async def chat_vision(
    prompt: str,
    image_path: Path,
    model: str | None = None,
    response_format: dict | None = None,
) -> str:
    """Send a text prompt plus an image (from file) to a vision-capable model."""
    model = model or config.EXTRACTION_MODEL
    suffix = image_path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/jpeg")

    image_data = base64.b64encode(image_path.read_bytes()).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}},
            ],
        }
    ]
    return await chat(messages=messages, model=model, response_format=response_format)


async def chat_vision_json(prompt: str, image_path: Path, model: str | None = None) -> dict:
    raw = await chat_vision(
        prompt=prompt,
        image_path=image_path,
        model=model,
        response_format={"type": "json_object"},
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)
