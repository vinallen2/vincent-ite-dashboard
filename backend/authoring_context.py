"""Bounded, evidence-grounded D1 context for OpenAI authoring.

Only existing first attempts count as performance. Historical aggregate-only
records are not reconstructed as individual answers.
"""
import json
from datetime import date

async def build_authoring_context(db, *, today: str, kind: str = "daily") -> dict:
    if kind not in ("daily", "bonus"):
        raise ValueError("Unsupported session kind")
    date.fromisoformat(today)
    sessions = await db.all("SELECT id,date,payload FROM study_sessions ORDER BY date DESC LIMIT 120")
    attempts = await db.all(
        "SELECT a.session_id,a.answers,a.result,a.submitted_at,s.payload AS session_payload "
        "FROM study_attempts a JOIN study_sessions s ON s.id=a.session_id "
        "ORDER BY a.submitted_at DESC LIMIT 60"
    )
    reviews = await db.all(
        "SELECT topic,due_date,reason,status,last_evidence FROM study_reviews "
        "WHERE status IN ('Planned','Backlog') ORDER BY due_date LIMIT 40"
    )
    prior = []
    for row in sessions:
        p = json.loads(row["payload"])
        for q in p.get("questions", []):
            prior.append({"date": row["date"], "domain": q.get("domain"),
                          "topic": q.get("topic"), "objective": q.get("objective")})
    recent = []
    topic_stats = {}
    for row in attempts:
        result = json.loads(row["result"])
        for q in result.get("questions", []):
            topic = q.get("topic") or "Uncategorized"
            stat = topic_stats.setdefault(topic, {"correct": 0, "total": 0, "uncertain": 0})
            stat["total"] += 1
            stat["correct"] += int(bool(q.get("correct")))
            stat["uncertain"] += int(q.get("confidence") in ("unsure", "guessed"))
            if len(recent) < 30:
                recent.append({"date": result.get("completionDate"), "topic": topic,
                               "objective": q.get("objective"), "correct": bool(q.get("correct")),
                               "confidence": q.get("confidence"),
                               "errorType": q.get("errorType")})
    return {
        "date": today, "kind": kind,
        "instructions": "Prioritize missed/uncertain objectives; avoid duplicating prior scored objectives. "
                        "Do not interpret an incorrect choice as a known reasoning error.",
        "topic_performance": topic_stats,
        "recent_attempts": recent,
        "prior_objectives": prior[:360],
        "due_reviews": [dict(topic=r["topic"], due_date=r.get("due_date"),
                             reason=r.get("reason")) for r in reviews if not r.get("due_date") or r["due_date"] <= today],
        "upcoming_reviews": [dict(topic=r["topic"], due_date=r.get("due_date"))
                             for r in reviews if r.get("due_date") and r["due_date"] > today][:15],
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
        q["id"] = str(i)
        questions.append(q)
    payload = {
        "id": prefix + today, "date": today, "kind": kind,
        "title": draft.get("title"), "teaching": draft.get("teaching"),
        "questions": questions, "review": draft.get("review", []),
    }
    return validate_session(payload)
