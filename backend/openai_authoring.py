"""OpenAI question authoring client. Does not run until explicitly called.

The API key stays in Railway. Questions are educational ITE-style practice,
not official ABA items; their clinical content merits independent review.
"""
import json
import logging
import os
import httpx

MODEL = os.getenv("OPENAI_ITE_MODEL", "gpt-6.2-astra")
ENDPOINT = "https://api.openai.com/v1/responses"

SYSTEM = """Write ORIGINAL practice questions modeled on the American Board of
Anesthesiology In-Training Examination (ITE), appropriate for a CA-2 resident.
These are not official ABA or TrueLearn questions.

Apply the supplied three topic assignments EXACTLY in order, including domain,
topic, difficulty and basic/advanced level. Do not independently choose topics.

Use the published ABA ITE format: single-best-answer A-type questions, usually
a concise clinical vignette or physiologic scenario followed by one clear lead-in
and exactly THREE responses (A, B, C). Questions test application of knowledge,
not obscure trivia or forced difficulty. Reflect both basic sciences and advanced
clinical anesthesia; the assignments already balance that over days.

Make distractors plausible to a trained anesthesiology resident and mutually
exclusive. Verify numerical calculations, normal ranges, pharmacology,
physiology, and internal consistency before writing the answer key. There must
be one defensible best answer with no hidden assumptions. No copy/paste or
cosmetic rewrites of previous question stems. Explain why the correct answer
is best and WHY each distractor is incorrect. Keep rationales concise and
educational; never add references or citations.

Start with an efficient high-yield teaching review covering the THREE assigned
objectives before the questions, without giving away a specific answer. If a
separate due_recall topic is supplied, add a brief retrieval-review paragraph
without repeating an old scored question. Teaching is not part of the score.
Write exactly three items: two application and one integration as assigned.
Return ONLY the requested JSON object."""

async def draft_session(context: dict, *, kind: str = "daily", model: str | None = None) -> dict:
    """Draft only; caller must validate and verify before persisting."""
    if kind not in ("daily", "bonus"):
        raise ValueError("kind must be daily or bonus")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    selected_model = model or MODEL
    use_reasoning = selected_model.startswith("gpt-6")
    from .question_plan import make_question_plan, normalized, stem_is_repeated
    assigned_questions = make_question_plan(context)
    from datetime import date
    from .question_plan import same_concept

    due = [row for row in context.get("due_reviews", [])
           if not any(same_concept(row["topic"], item["topic"])
                      for item in assigned_questions)]
    # Rotate the overdue pool so the same missed item is not lectured on daily.
    if due:
        shift = date.fromisoformat(context["date"]).toordinal() % len(due)
        due = (due[shift:] + due[:shift])[:2]
    due_recall = [
        {"topic": x["topic"], "reason": x["reason"]}
        for x in due
    ]
    prompt = json.dumps({
        "task": "CA-2 ABA ITE practice: teaching first, then three exam-style questions",
        "assigned_questions": assigned_questions,
        "due_recall": due_recall,
        "output_shape": {
            "title": "brief session title",
            "teaching": "concise pre-question review of assigned concepts and due recall",
            "review": [],
            "questions": [{
                "stem": "single-best-answer item", "domain": "exact assigned domain",
                "topic": "exact assigned topic", "objective": "specific tested skill",
                "difficulty": "exact assigned difficulty", "level": "exact assigned level",
                "answer": "A/B/C",
                "options": [
                    {"id": "A", "text": "plausible answer", "explanation": "why right or wrong"},
                    {"id": "B", "text": "plausible answer", "explanation": "why right or wrong"},
                    {"id": "C", "text": "plausible answer", "explanation": "why right or wrong"}
                ]
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
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
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
                    "Use exactly three complete A/B/C options per question, "
                    "each with a concise rationale and one unambiguous best answer."
                )
            payload = {
                "model": selected_model,
                "instructions": SYSTEM,
                "input": "Return only a valid JSON object matching the requested output shape.\n"
                         + prompt + correction,
                "max_output_tokens": 25000 if use_reasoning else 5000,
                "text": {"format": {"type": "json_object"}}
            }
            if use_reasoning:
                payload["reasoning"] = {"effort": "high"}
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
                    if question.get("difficulty") != focus["difficulty"]:
                        raise ValueError("Incorrect application/integration assignment")
                    if question.get("level") != focus["level"]:
                        raise ValueError("Incorrect basic/advanced assignment")
                    if stem_is_repeated(question.get("stem", ""), context.get("previous_stems", [])):
                        raise ValueError("Rephrased or recycled question stem")
                    opts = question.get("options", [])
                    if sorted(o.get("id") for o in opts) != ["A", "B", "C"]:
                        raise ValueError("Each question needs three A/B/C options")
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
