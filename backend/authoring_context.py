"""Bounded, evidence-grounded D1 context for OpenAI authoring.

Only existing first attempts count as performance. Historical aggregate-only
records are not reconstructed as individual answers.
"""
import json
from datetime import date

async def build_authoring_context(db, *, today: str, kind: str = "daily") -> dict:
    """Use actual D1 answers and review records; only Python sees full history."""
    from .spaced_repetition import plan_spaced_repetition

    if kind not in ("daily", "bonus"):
        raise ValueError("Unsupported session kind")
    date.fromisoformat(today)
    sessions = await db.all(
        "SELECT id,date,payload FROM study_sessions ORDER BY date DESC,created_at DESC LIMIT 150"
    )
    attempts = await db.all(
        "SELECT result FROM study_attempts ORDER BY submitted_at DESC LIMIT 150"
    )
    reviews = await db.all(
        "SELECT topic,due_date,reason,status,last_evidence FROM study_reviews "
        "WHERE status IN ('Planned','Backlog') ORDER BY due_date LIMIT 200"
    )
    legacy_row = await db.one("SELECT value FROM study_state WHERE key='legacy'")
    historical = []
    if legacy_row:
        for record in json.loads(legacy_row["value"]).get("tabs", {}).get("Question Log", [])[1:]:
            if len(record) >= 10 and record[4]:
                historical.append({
                    "date": record[0], "domain": record[3], "topic": record[4],
                    "correct": str(record[7]).strip() in ("1", "true", "True"),
                })

    used_today = []
    prior = []
    stems = []
    for row in sessions:
        payload = json.loads(row["payload"])
        for question in payload.get("questions", []):
            topic = str(question.get("topic") or "").strip()
            objective = str(question.get("objective") or "").strip()
            prior.append({
                "date": row["date"], "domain": question.get("domain"),
                "topic": topic, "objective": objective,
            })
            if row["date"] == today and topic:
                used_today.append(topic)
            try:
                age = (date.fromisoformat(today) - date.fromisoformat(row["date"])).days
            except (ValueError, TypeError):
                age = 1000
            if 0 <= age <= 30 and question.get("stem"):
                stems.append(question["stem"])

    results = [json.loads(row["result"]) for row in attempts]
    due = plan_spaced_repetition(results, reviews, today=today, used_today=used_today)
    return {
        "date": today, "kind": kind,
        "prior_objectives": prior[:450],
        "historical_question_log": historical[-80:],
        "previous_stems": stems[:120],
        "already_tested_today": {
            "topics": used_today,
            "objectives": [
                item["objective"] for item in prior
                if item["date"] == today and item["objective"]
            ],
        },
        # This is the only spaced-review list the authoring prompt receives.
        "due_reviews": due,
    }


def prepare_session(draft: dict, *, today: str, kind: str = "daily") -> dict:
    """Map an AI draft to the exact immutable website publication contract."""
    from .service import validate_session
    if kind not in ("daily", "bonus"):
        raise ValueError("Unsupported session kind")
    prefix = "CA2-Bonus " if kind == "bonus" else "CA2-New "
    questions = []
    for i, question in enumerate(draft.get("questions", []), 1):
        q = dict(question)
        q.pop("sources", None)  # Do not publish AI-generated question references.
        q["id"] = str(i)
        questions.append(q)
    payload = {
        "id": prefix + today, "date": today, "kind": kind,
        "title": draft.get("title"), "teaching": draft.get("teaching"),
        "questions": questions, "review": draft.get("review", []),
    }
    return validate_session(payload)
