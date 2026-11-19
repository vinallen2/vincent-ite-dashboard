"""OpenAI question authoring client. Does not run until explicitly called.

The API key stays in Railway. Clinical questions require source verification
and human/independent quality checks before publication.
"""
import json
import os
import httpx

MODEL = os.getenv("OPENAI_ITE_MODEL", "gpt-4.1-mini")
ENDPOINT = "https://api.openai.com/v1/responses"

SYSTEM = """You are authoring original CA-2 anesthesiology ITE practice material.
Return a valid JSON object only. Begin with a concise teaching review that does not reveal
answers. Write exactly three clinically realistic, challenging multiple-choice
questions, each with exactly three answer options labeled A, B, C (or four labeled A, B, C, D), with one unambiguously correct answer each. Two must test application
and one integration. Give substantive rationales for all answer choices.
Avoid repeated objectives supplied in context. Do not invent article citations,
DOIs, guidelines, or URLs. Include at least one HTTPS source per question;\nprefer stable, well-known primary references and flag uncertain citations.
These are educational practice questions, not official ABA items."""

async def draft_session(context: dict, *, kind: str = "daily", model: str | None = None) -> dict:
    """Draft only; caller must validate and verify before persisting."""
    if kind not in ("daily", "bonus"):
        raise ValueError("kind must be daily or bonus")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    prompt = json.dumps({
        "task": "Prepare a review-first CA-2 ITE session",
        "kind": kind,
        "performance_and_previous_objectives": context,
        "output_shape": {
            "title": "string",
            "teaching": "string",
            "review": [],
            "questions": [{
                "stem": "string", "domain": "string", "topic": "string",
                "objective": "string", "difficulty": "application or integration",
                "level": "basic or advanced", "answer": "A, B, C, or D",
                "options": [{"id": "A", "text": "string", "explanation": "string"}],
                "sources": [{"title": "string", "url": "https://source.example/path"}]
            }]
        }
    }, ensure_ascii=False)
    payload = {
        "model": model or MODEL,
        "instructions": SYSTEM,
        "input": "Return only a valid JSON object matching the requested output shape.\n" + prompt,
        "max_output_tokens": 5000,
        "text": {"format": {"type": "json_object"}}
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(55.0, connect=10.0)) as client:
        response = await client.post(ENDPOINT, headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }, json=payload)
        if response.status_code >= 400:
            try:
                detail = response.json().get('error', {})
                message = str(detail.get('message', 'OpenAI rejected the request'))[:500]
                code = str(detail.get('code', 'unknown'))[:100]
            except (ValueError, AttributeError):
                message, code = 'OpenAI rejected the request', 'unknown'
            raise RuntimeError(f'OpenAI API HTTP {response.status_code}, code={code}: {message}')
        data = response.json()
    if data.get("status") != "completed":
        raise RuntimeError("OpenAI response was not completed")
    parts = [item.get("text", "") for output in data.get("output", [])
             for item in output.get("content", []) if item.get("type") == "output_text"]
    if not parts:
        raise RuntimeError("OpenAI returned no text")
    draft = json.loads("".join(parts))
    questions = draft.get("questions", [])
    if len(questions) != 3 or not draft.get("teaching"):
        raise ValueError("Invalid draft: requires teaching and exactly three questions")
    for question in questions:
        opts = question.get("options", [])
        if sorted(o.get("id") for o in opts) != ["A", "B", "C"]:
            raise ValueError("Each question must have A/B/C or A/B/C/D choices")
        if question.get("answer") not in ("A", "B", "C", "D"):
            raise ValueError("Invalid answer key")
        if not all(o.get("explanation") for o in opts):
            raise ValueError("Every option requires an explanation")
    return draft
