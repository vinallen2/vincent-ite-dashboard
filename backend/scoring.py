"""Pure scoring helpers. Never overwrite a submitted first attempt."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


@dataclass(frozen=True)
class QuestionResult:
    question_id: str
    choice: str
    correct: bool
    confidence: str | None
    next_review: str


def grade_first_attempt(
    questions: Iterable[dict], answers: Iterable[dict], submitted_on: date
) -> list[QuestionResult]:
    """Validate all three observed answers and return deterministic grading.

    Persistence must enforce uniqueness for (session_id, question_id) and
    (session_id, first_attempt). This function does not write to a database.
    """
    questions = list(questions)
    answers = list(answers)
    if len(questions) != 3 or len(answers) != 3:
        raise ValueError("A scored session requires exactly three questions and answers")
    keys = {str(q["id"]): q["answer"].upper() for q in questions}
    if len(keys) != 3:
        raise ValueError("Duplicate question IDs")
    ids = [str(a["questionId"]) for a in answers]
    if len(set(ids)) != 3 or set(ids) != set(keys):
        raise ValueError("Answers must match the exact published question IDs")
    results = []
    for answer in answers:
        qid = str(answer["questionId"])
        choice = str(answer["choice"]).upper()
        if choice not in {"A", "B", "C", "D"}:
            raise ValueError("Invalid choice")
        question = next(q for q in questions if str(q["id"]) == qid)
        valid = {str(o["id"]).upper() for o in question["options"]}
        if choice not in valid:
            raise ValueError("Choice not present in published question")
        confidence = answer.get("confidence") or None
        if confidence not in (None, "sure", "unsure", "guessed"):
            raise ValueError("Invalid confidence")
        correct = choice == keys[qid]
        interval = 3 if correct and confidence not in ("unsure", "guessed") else 1
        results.append(QuestionResult(qid, choice, correct, confidence,
                                      (submitted_on + timedelta(days=interval)).isoformat()))
    return results


def accuracy(correct: int, total: int) -> float | None:
    return round(100 * correct / total, 1) if total else None
