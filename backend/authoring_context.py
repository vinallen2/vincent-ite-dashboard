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
    # Prior website sessions, including generated sessions that have not yet been answered.
    # This prevents consecutive bonus sessions from recycling the same objectives.
    legacy_row = await db.one("SELECT value FROM study_state WHERE key='legacy'")
    historical_questions = []
    if legacy_row:
        tabs = json.loads(legacy_row["value"]).get("tabs", {})
        for row in tabs.get("Question Log", [])[1:]:
            if len(row) >= 10 and row[4]:
                historical_questions.append({
                    "date": row[0], "domain": row[3], "topic": row[4],
                    "correct": str(row[7]).strip().lower() in ("1", "true"),
                    "confidence": row[8], "errorType": row[9],
                })
    today_topics = set()
    today_objectives = set()
    recent_topics = []
    prior = []
    previous_stems = []
    for row in sessions:
        p = json.loads(row["payload"])
        for q in p.get("questions", []):
            topic = (q.get("topic") or "").strip()
            objective = (q.get("objective") or "").strip()
            prior.append({"date": row["date"], "domain": q.get("domain"),
                          "topic": topic, "objective": objective})
            try:
                age = (date.fromisoformat(today) - date.fromisoformat(row["date"])).days
            except (ValueError, TypeError):
                age = 1000
            if 0 <= age < 30 and q.get("stem"):
                previous_stems.append(q["stem"])
            if row["date"] == today:
                if topic:
                    today_topics.add(topic.casefold())
                if objective:
                    today_objectives.add(objective.casefold())
            if topic and len(recent_topics) < 36:
                recent_topics.append({"date": row["date"], "topic": topic, "domain": q.get("domain")})
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
    for h in historical_questions:
        topic = h["topic"] or "Uncategorized"
        stat = topic_stats.setdefault(topic, {"correct": 0, "total": 0, "uncertain": 0})
        stat["total"] += 1
        stat["correct"] += int(h["correct"])
        stat["uncertain"] += int(str(h.get("confidence") or "").lower() in ("low", "unsure", "guessed"))
    due = [
        dict(topic=r["topic"], due_date=r.get("due_date"), reason=r.get("reason"))
        for r in reviews
        if (not r.get("due_date") or r["due_date"] <= today)
        and (r.get("topic") or "").strip().casefold() not in today_topics
    ]
    return {
        "date": today, "kind": kind,
        "instructions": "Prioritize missed/uncertain objectives; avoid duplicating prior scored objectives. "
                        "Do not interpret an incorrect choice as a known reasoning error.",
        "topic_performance": topic_stats,
        "recent_attempts": recent,
        "historical_question_log": historical_questions[-60:],
        "prior_objectives": prior[:360],
        "previous_stems": previous_stems[:90],
        "recently_used_topics": recent_topics,
        "already_tested_today": {
            "topics": sorted(today_topics),
            "objectives": sorted(today_objectives),
        },
        "due_reviews": due[:20],
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
        q.pop("sources", None)  # Do not publish AI-generated question references.
        q["id"] = str(i)
        questions.append(q)
    payload = {
        "id": prefix + today, "date": today, "kind": kind,
        "title": draft.get("title"), "teaching": draft.get("teaching"),
        "questions": questions, "review": draft.get("review", []),
    }
    return validate_session(payload)
