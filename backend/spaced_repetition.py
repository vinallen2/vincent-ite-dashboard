"""Read study evidence from D1 records and calculate due concepts in Python.

The OpenAI prompt gets only a short, deterministic review plan. One concept
may appear in the scored set after a cooldown; newer due concepts are taught
through brief retrieval practice instead of near-duplicate scored stems.
"""
from collections import defaultdict
from datetime import date, timedelta

from .question_plan import normalized, same_concept

INTERVALS = (3, 7, 14, 30, 45)


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def plan_spaced_repetition(attempt_results, review_rows, *, today, used_today=()):
    """Pure, reproducible due-date scheduling from first-attempt records.

    Each distinct question topic gets one schedule based on its latest graded
    encounter, not one task per prior attempt or each stale review row.
    Correct confirmed retrievals extend the interval; misses/uncertainty reset
    it to the next day. This is a heuristic, not a claim about mastery.
    """
    target = _day(today)
    if target is None:
        raise ValueError("Valid calendar date required")
    encountered = defaultdict(list)
    for result in attempt_results:
        stamp = _day(result.get("completionDate") or result.get("sessionDate"))
        if not stamp or stamp > target:
            continue
        for q in result.get("questions", []):
            topic = str(q.get("topic") or "").strip()
            if topic:
                encountered[normalized(topic)].append({
                    "date": stamp, "topic": topic, "correct": bool(q.get("correct")),
                    "confidence": str(q.get("confidence") or "").casefold(),
                })
    ranked = []
    active_topics = []
    for values in encountered.values():
        values.sort(key=lambda r: r["date"])
        latest = values[-1]
        # A correct but uncertain answer is not a successful retrieval.
        streak = 0
        for event in reversed(values):
            if not event["correct"] or event["confidence"] in ("unsure", "guessed", "low"):
                break
            streak += 1
        interval = INTERVALS[min(streak - 1, len(INTERVALS) - 1)] if streak else 1
        due = latest["date"] + timedelta(days=interval)
        active_topics.append(latest["topic"])
        if due <= target and not any(same_concept(latest["topic"], t) for t in used_today):
            ranked.append({
                "topic": latest["topic"], "due_date": due.isoformat(),
                "last_tested": latest["date"].isoformat(),
                "priority": 100 if streak == 0 else 60,
                "reason": "incorrect/uncertain" if streak == 0 else "spaced retention",
                "scored_eligible": (target - latest["date"]).days >= 14,
            })
    # Historical/migrated review plans without corresponding scored items.
    for row in review_rows:
        if row.get("status") not in ("Planned", "Backlog"):
            continue
        topic = str(row.get("topic") or "").strip()
        if not topic or any(same_concept(topic, t) for t in active_topics):
            continue
        if any(same_concept(topic, t) for t in used_today):
            continue
        due = _day(row.get("due_date"))
        if due and due > target:
            continue
        if any(same_concept(topic, item["topic"]) for item in ranked):
            continue
        evidence = _day(row.get("last_evidence"))
        ranked.append({
            "topic": topic, "due_date": due.isoformat() if due else target.isoformat(),
            "last_tested": evidence.isoformat() if evidence else None,
            "priority": 75 if "incorrect" in (row.get("reason") or "").lower() else 45,
            "reason": str(row.get("reason") or "historical review")[:90],
            "scored_eligible": bool(evidence and (target - evidence).days >= 14),
        })
    ranked.sort(key=lambda r: (-r["priority"], r["due_date"], r["topic"]))
    return ranked[:15]
