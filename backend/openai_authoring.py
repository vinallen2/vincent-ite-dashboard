"""OpenAI question authoring client. Does not run until explicitly called.

The API key stays in Railway. Clinical questions require source verification
and human/independent quality checks before publication.
"""
import json
import logging
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
These are educational practice questions, not official ABA items.
IMPORTANT: The question topics and domains are ASSIGNED by the application. You must write
Question 1, Question 2 and Question 3 in exactly the order of assigned_questions. Copy
each assigned domain and topic string VERBATIM into that question's domain and topic
fields. You MAY NOT substitute a topic from recent history or change an assigned topic.
No recycled question stems, only changing the patient's age, numeric values or vignette
while preserving the same reasoning step. Use distinct clinical settings and test a new
decision or inference in each question. Realistic high-yield CA-2 / February 2027 ITE
difficulty, one unambiguous key, four plausible choices (A through D), no tricks or
misleading clues. The pre-question teaching should explain core principles, but not
reveal the keyed answers or rehearse an identical numerical problem. Include one short
spaced-recall concept in that teaching when due_reviews is non-empty, without turning
a concept tested in the last 14 days into another scored question. Treat due_reviews
as TEACHING / RETENTION material, NOT a directive to replace assigned questions.
Never invent DOIs, guideline URLs, primary sources, or references."""

async def draft_session(context: dict, *, kind: str = "daily", model: str | None = None) -> dict:
    """Draft only; caller must validate and verify before persisting."""
    if kind not in ("daily", "bonus"):
        raise ValueError("kind must be daily or bonus")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    from .question_plan import make_question_plan, normalized, stem_is_repeated
    assigned_questions = make_question_plan(context)
    prompt = json.dumps({
        "task": "Prepare a review-first CA-2 ITE session",
        "kind": kind,
        "assigned_questions": assigned_questions,
        "performance_and_previous_objectives": context,
        "selection_requirements": {
            "count": 3,
            "unique_anesthesia_domains": 3,
            "last_14_days_topic_repetition": "forbidden for scored questions",
            "due_for_spaced_review": "review briefly in teaching, not by recycling a scored stem",
            "other_questions": "only the three assigned topics, each in the specified domain",
            "prior_stem_reuse": "forbidden",
            "source_quality": "reliable reference URLs, do not fabricate citations"
        },
        "output_shape": {
            "title": "string",
            "teaching": "string",
            "review": [],
            "questions": [{
                "stem": "string", "domain": "string", "topic": "string",
                "objective": "string", "difficulty": "application or integration",
                "level": "basic or advanced", "answer": "A, B, C, or D",
                "options": [{"id": "A", "text": "string", "explanation": "string"}, {"id": "B", "text": "string", "explanation": "string"}, {"id": "C", "text": "string", "explanation": "string"}, {"id": "D", "text": "string", "explanation": "string"}],
                "sources": [{"title": "string", "url": "https://source.example/path"}]
            }]
        }
    }, ensure_ascii=False)
    # The model can produce a clinically plausible draft that duplicates a topic.
    # Correct it automatically instead of surfacing a server error to the learner.
    from .authoring_context import prepare_session
    from .service import StudyError

    previous_topics = {
        str(t).strip().casefold()
        for t in context.get("already_tested_today", {}).get("topics", [])
    }
    previous_objectives = {
        str(o).strip().casefold()
        for o in context.get("already_tested_today", {}).get("objectives", [])
    }
    rejected_topics = set()
    feedback = ""
    logger = logging.getLogger("ite.generation")
    async with httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=10.0)) as client:
        for attempt in range(3):
            draft = None
            correction = ""
            if attempt:
                correction = (
                    "\nREGENERATE THE ENTIRE THREE-QUESTION SET. "
                    "The previous draft failed quality controls: " + feedback + ". "
                    "Choose NEW topics and three distinct domains. "
                    "Do not use these rejected topics: "
                    + json.dumps(sorted(rejected_topics), ensure_ascii=False) + ". "
                    "Follow assigned_questions exactly; copy topics and domains verbatim. "
                    "Avoid all topics tested in the previous 14 days. "
                    "Use three or four complete A/B/C(/D) options per question, "
                    "with rationale and HTTPS source for each question."
                )
            payload = {
                "model": model or MODEL,
                "instructions": SYSTEM,
                "input": "Return only a valid JSON object matching the requested output shape.\n"
                         + prompt + correction,
                "max_output_tokens": 5000,
                "text": {"format": {"type": "json_object"}}
            }
            response = await client.post(ENDPOINT, headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }, json=payload)
            if response.status_code >= 400:
                try:
                    detail = response.json().get("error", {})
                    message = str(detail.get("message", "OpenAI rejected the request"))[:500]
                    code = str(detail.get("code", "unknown"))[:100]
                except (ValueError, AttributeError):
                    message, code = "OpenAI rejected the request", "unknown"
                raise RuntimeError(
                    f"OpenAI API HTTP {response.status_code}, code={code}: {message}"
                )
            data = response.json()
            try:
                if data.get("status") != "completed":
                    raise ValueError("OpenAI response was not completed")
                parts = [
                    item.get("text", "")
                    for output in data.get("output", [])
                    for item in output.get("content", [])
                    if item.get("type") == "output_text"
                ]
                if not parts:
                    raise ValueError("OpenAI returned no text")
                draft = json.loads("".join(parts))
                questions = draft.get("questions", [])
                if len(questions) != 3 or not draft.get("teaching"):
                    raise ValueError("Teaching and exactly three questions are required")
                seen_topics = set()
                seen_domains = set()
                for index, question in enumerate(questions):
                    focus = assigned_questions[index]
                    if normalized(question.get("domain")) != normalized(focus["domain"]):
                        raise ValueError(f"Question {index+1} must use domain {focus['domain']}")
                    if normalized(question.get("topic")) != normalized(focus["topic"]):
                        raise ValueError(f"Question {index+1} must use exact topic {focus['topic']}")
                    if stem_is_repeated(question.get("stem", ""), context.get("previous_stems", [])):
                        raise ValueError("Rephrased or recycled question stem")
                    opts = question.get("options", [])
                    if sorted(o.get("id") for o in opts) not in (
                        ["A", "B", "C"], ["A", "B", "C", "D"]
                    ):
                        raise ValueError("Each question needs A/B/C or A/B/C/D options")
                    if question.get("answer") not in {o["id"] for o in opts}:
                        raise ValueError("Invalid answer key")
                    if not all(o.get("explanation") for o in opts):
                        raise ValueError("Every choice needs an explanation")
                    topic = str(question.get("topic") or "").strip().casefold()
                    objective = str(question.get("objective") or "").strip().casefold()
                    domain = str(question.get("domain") or "").strip().casefold()
                    if not topic or topic in previous_topics or topic in seen_topics:
                        raise ValueError(f"Repeated or missing topic: {topic}")
                    if not objective or objective in previous_objectives:
                        raise ValueError(f"Repeated or missing objective: {objective}")
                    seen_topics.add(topic)
                    seen_domains.add(domain)
                if len(seen_domains) != 3:
                    raise ValueError("Questions must span three distinct domains")
                # Check the complete publication contract before returning.
                prepare_session(draft, today=context["date"], kind=kind)
                return draft
            except (ValueError, TypeError, KeyError, StudyError) as exc:
                feedback = str(exc)[:250]
                logger.warning("ITE draft %s/3 rejected: %s", attempt + 1, feedback)
                if isinstance(draft, dict):
                    rejected_topics.update(
                        str(q.get("topic") or "").strip().casefold()
                        for q in draft.get("questions", []) if isinstance(q, dict)
                    )
                if attempt == 2:
                    raise ValueError(
                        "Unable to produce three non-repeating valid ITE questions "
                        "after three automatic drafts"
                    ) from exc
    raise RuntimeError("Generation unexpectedly finished without a draft")
