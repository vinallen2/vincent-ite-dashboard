"""Synthetic fixtures only. These tests never contact a production database."""
import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from backend.app import create_app
from backend.local import SQLiteStore
from backend.service import StudyService, StudyError, grade


def session(kind='daily', day='2026-11-19', options='ABC'):
    return dict(id=('CA2-Bonus ' if kind=='bonus' else 'CA2-New ')+day,kind=kind,date=day,title='Synthetic arithmetic fixture',teaching='Fixture teaching only.',review=[],questions=[dict(id=str(i),stem='Synthetic arithmetic fixture',domain='Fixture',topic='Fixture '+str(i),objective='Fixture objective '+str(i),difficulty='integration' if i==3 else 'application',level='basic',answer='B',options=[dict(id=c,text=c,explanation='Fixture explanation') for c in options],sources=[dict(title='Fixture reference',url='https://example.org')]) for i in range(1,4)])


def answers(choices='BAB'):
    return [dict(questionId=str(i),choice=c,confidence='unsure' if i==3 else '') for i,c in enumerate(choices,1)]


def setup():
    db = SQLiteStore()
    db.conn.executescript(Path('migrations/0001_initial.sql').read_text())
    base = dict(source={},tabs={'Sessions':[['Date','Assessment','Status','Questions','Correct','Daily session complete?','Confidence coverage','Notes'],['2026-11-18','Aggregate','Verified','20','19','No','','']], 'Question Log':[['Date','Set','Question','ABA domain','Subtopic','Your answer','Correct answer','Correct?','Confidence','Error type','Notes']], 'Dashboard':[[None,''] for _ in range(9)]})
    db.conn.execute('INSERT INTO study_state VALUES (?,?,?)',('legacy',json.dumps(base),'2026-11-19'))
    db.conn.commit()
    return db, StudyService(db,lambda:datetime(2026,11,20,2,0,tzinfo=timezone.utc))


def test_persistence_idempotency_and_combined_scores():
    async def run():
        db,s = setup()
        daily, extra = session(),session('bonus')
        await s.publish(daily)
        await s.publish(extra)
        unopened = await s.public_data()
        assert unopened['performance']['tabs']['Dashboard'][4][1]=='20'
        for q in unopened['sessions'][0]['questions']:
            assert 'answer' not in q and 'explanation' not in q['options'][0]
        assert unopened['sessions'][0]['teaching']==''
        first = await s.save_answers(dict(sessionId=daily['id'],answers=answers()))
        repeat = await s.save_answers(dict(sessionId=daily['id'],answers=answers('CCC')))
        assert first == repeat
        assert first['attempt']['result']['correct']==2
        assert first['attempt']['result']['completionDate']=='2026-11-19'
        assert first['attempt']['result']['questions'][2]['nextReview']=='2026-11-20'
        await s.save_answers(dict(sessionId=extra['id'],answers=answers('BBB')))
        p = await s.performance()
        assert p['tabs']['Dashboard'][4][1]=='26'
        assert p['tabs']['Dashboard'][5][1]=='24'
        assert [r[5] for r in p['tabs']['Sessions'][2:]]==['Yes','No']
        assert len(await db.all('SELECT * FROM study_attempts'))==2
        assert len(await db.all('SELECT * FROM study_reviews'))==6
        changed = copy.deepcopy(daily)
        changed['questions'][0]['answer']='A'
        with pytest.raises(StudyError) as e: await s.publish(changed)
        assert e.value.status==409
    asyncio.run(run())


def test_article_dedup_and_pending_acknowledgment():
    async def run():
        db,s=setup()
        d=session(options='ABCD')
        await s.publish(d)
        a=await s.save_answers(dict(sessionId=d['id'],answers=answers()))
        await s.action('mark_reviewed',dict(attemptId=a['attempt']['id'],summary='Fixture planning note'))
        assert (await s.context())['pending']==[]
        article=dict(date='2026-11-19',title='Synthetic article title',doi='https://doi.org/10.0000/FIXTURE',url='https://example.org',status='Prepared')
        first=await s.record_article(article)
        article.update(title='Different synthetic title',doi='doi: 10.0000/fixture')
        assert (await s.record_article(article))['id']==first['id']
        article.update(title='Synthetic article title!',doi='10.0000/other')
        assert (await s.record_article(article))['id']==first['id']
        assert len(await db.all('SELECT * FROM study_articles'))==1
    asyncio.run(run())


def test_authentication_and_request_guards():
    async def run():
        db,s=setup()
        app=create_app(db,'fixture-secret')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://private.example') as c:
            assert (await c.get('/api/study')).status_code==401
            assert (await c.get('/api/study',headers={'oai-authenticated-user-id':'spoofed'})).status_code==401
            h={'x-ite-gateway-token':'fixture-secret'}
            assert (await c.get('/api/study',headers=h)).status_code==200
            assert (await c.post('/api/submit',headers=h,json={})).status_code==401
            assert (await c.post('/api/agent',headers={**h,'origin':'https://evil.example'},json={'action':'context'})).status_code==403
            assert (await c.post('/api/agent',headers=h,content='invalid')).status_code==400
            assert (await c.post('/api/agent',headers=h,content='x'*250001)).status_code==413
            assert (await c.get('/docs',headers=h)).status_code==404
    asyncio.run(run())


def test_new_york_submission_date_and_choice_validation():
    r=grade(session(),answers(),'2026-11-20T02:00:00Z')
    assert r['completionDate']=='2026-11-19'
    with pytest.raises(StudyError): grade(session(),answers('DDD'),'2026-11-20T02:00:00Z')
    bad=answers();bad[1]['questionId']='1'
    with pytest.raises(StudyError): grade(session(),bad,'2026-11-20T02:00:00Z')
