import asyncio
import json
from backend.authoring_context import build_authoring_context, prepare_session

class FakeDB:
    async def all(self, sql, *params):
        if "FROM study_sessions" in sql:
            return [{"id":"CA2-New 2026-11-18","date":"2026-11-18",
                     "payload":json.dumps({"questions":[{"domain":"Pulmonary","topic":"Ventilation","objective":"Fresh gas flow"}]})}]
        if "FROM study_attempts" in sql:
            return [{"session_id":"CA2-New 2026-11-18","answers":"[]",
                     "result":json.dumps({"completionDate":"2026-11-18","questions":[
                         {"topic":"Ventilation","objective":"Fresh gas flow","correct":False,"confidence":"unsure"}]})}]
        return [{"topic":"Ventilation","due_date":"2026-11-19","reason":"Missed","status":"Planned","last_evidence":None}]

def test_context_uses_actual_attempts():
    result=asyncio.run(build_authoring_context(FakeDB(),today="2026-11-19"))
    assert result["topic_performance"]["Ventilation"] == {"correct":0,"total":1,"uncertain":1}
    assert result["due_reviews"][0]["topic"] == "Ventilation"
    assert result["prior_objectives"][0]["objective"] == "Fresh gas flow"

def test_prepare_session_matches_website_contract():
    q={"stem":"Which statement is correct?","domain":"Cardiac","topic":"Preload",
       "objective":"Interpret preload","difficulty":"application","level":"advanced",
       "answer":"B","options":[
           {"id":k,"text":"Option "+k,"explanation":"Explanation "+k} for k in "ABC"],
       "sources":[{"title":"Medical textbook","url":"https://example.org/source"}]}
    draft={"title":"Hemodynamics","teaching":"Review of venous return and preload.",
           "questions":[q,dict(q),dict(q)]}
    p=prepare_session(draft,today="2026-11-19")
    assert p["id"]=="CA2-New 2026-11-19"
    assert [q["id"] for q in p["questions"]]==["1","2","3"]
