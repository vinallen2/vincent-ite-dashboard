from datetime import date
import pytest
from backend.scoring import grade_first_attempt

QUESTIONS = [
    {"id": str(i), "answer": "B", "options": [{"id": c} for c in "ABC"]}
    for i in range(1, 4)
]


def test_first_attempt_and_review_intervals():
    answers = [
        {"questionId": "1", "choice": "B", "confidence": "sure"},
        {"questionId": "2", "choice": "A", "confidence": ""},
        {"questionId": "3", "choice": "B", "confidence": "unsure"},
    ]
    result = grade_first_attempt(QUESTIONS, answers, date(2026, 11, 19))
    assert [r.correct for r in result] == [True, False, True]
    assert [r.next_review for r in result] == ["2026-11-22", "2026-11-20", "2026-11-20"]


def test_rejects_partial_attempt():
    with pytest.raises(ValueError):
        grade_first_attempt(QUESTIONS, [{"questionId": "1", "choice": "B"}], date(2026, 11, 19))


def test_rejects_wrong_question_set():
    with pytest.raises(ValueError):
        grade_first_attempt(QUESTIONS, [
            {"questionId": "1", "choice": "B"},
            {"questionId": "2", "choice": "B"},
            {"questionId": "4", "choice": "B"},
        ], date(2026, 11, 19))

