"""Study rules ported from the production JavaScript API.

No medical questions or private performance records belong in source control.
First attempts are immutable, including across duplicate/racing submissions.
"""
import copy
import json
import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from .scoring import grade_first_attempt

EASTERN = ZoneInfo('America/New_York')
from .workflow import WORKFLOW


class StudyError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(value, limit=8000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def valid_date(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def bonus(session):
    return session.get('kind') == 'bonus' or session['id'].startswith('CA2-Bonus ')


def validate_session(p):
    if not isinstance(p, dict) or not valid_date(p.get('date')):
        raise StudyError('A valid session date is required.')
    expected = 'CA2-Bonus ' if p.get('kind') == 'bonus' or str(p.get('id', '')).startswith('CA2-Bonus ') else 'CA2-New '
    if p.get('id') != expected + p['date'] or p.get('kind', 'bonus' if expected == 'CA2-Bonus ' else 'daily') != ('bonus' if expected == 'CA2-Bonus ' else 'daily'):
        raise StudyError('Session id, kind, and date must match.')
    if not text(p.get('title'), 160) or not isinstance(p.get('questions'), list) or len(p['questions']) != 3:
        raise StudyError('A session requires a title and exactly three questions.')
    for i, q in enumerate(p['questions'], 1):
        if not isinstance(q, dict) or q.get('id') != str(i) or any(not text(q.get(k), n) for k, n in [('stem',8000),('domain',160),('topic',240),('objective',1000)]):
            raise StudyError(f'Invalid question {i}.')
        if q.get('difficulty') not in ('application', 'integration') or q.get('level') not in ('basic', 'advanced'):
            raise StudyError('Invalid question difficulty or level.')
        options = q.get('options')
        if not isinstance(options, list) or len(options) not in (3,4):
            raise StudyError('Use three or four options.')
        for j, option in enumerate(options):
            if option.get('id') != 'ABCD'[j] or not text(option.get('text'),2000) or not text(option.get('explanation'),5000):
                raise StudyError('Each option requires text and an explanation.')
        if q.get('answer') not in [o['id'] for o in options]:
            raise StudyError('Answer must be a published option.')
        sources = q.get('sources')
        if not isinstance(sources, list) or not sources or any(not text(s.get('title'),300) or not str(s.get('url','')).startswith('https://') for s in sources):
            raise StudyError('Each question requires verified HTTPS sources.')
    review = p.get('review')
    if not isinstance(review, list) or len(review) > 3 or any(any(not text(r.get(k),n) for k,n in [('topic',300),('prompt',2000),('explanation',6000)]) for r in review):
        raise StudyError('Review requires at most three topic, prompt, explanation records.')
    if not text(p.get('teaching'), 14000):
        raise StudyError('Focused teaching is required.')
    return p


def grade(session, answers, submitted_at):
    completion = datetime.fromisoformat(submitted_at.replace('Z','+00:00')).astimezone(EASTERN).date()
    try:
        scored = {r.question_id:r for r in grade_first_attempt(session['questions'],answers,completion)}
    except (ValueError, KeyError, TypeError) as e:
        raise StudyError(str(e)) from e
    results = []
    for q in session['questions']:
        s = scored[q['id']]
        results.append(dict(questionId=q['id'],choice=s.choice,confidence=s.confidence or 'Not provided',correct=s.correct,key=q['answer'],domain=q['domain'],topic=q['topic'],objective=q['objective'],difficulty=q['difficulty'],level=q['level'],errorType='None demonstrated' if s.correct else 'Undetermined; reasoning not supplied',nextReview=s.next_review))
    return dict(sessionId=session['id'],kind='bonus' if bonus(session) else 'daily',sessionDate=session['date'],completionDate=completion.isoformat(),submittedAt=submitted_at,correct=sum(r['correct'] for r in results),total=3,questions=results)


def view(session_row, attempt=None):
    p = json.loads(session_row['payload'])
    p['kind'] = 'bonus' if bonus(p) else 'daily'
    if not attempt:
        p['questions'] = [dict(id=q['id'],stem=q['stem'],options=[dict(id=o['id'],text=o['text']) for o in q['options']]) for q in p['questions']]
        p['review'], p['teaching'] = [], ''
    p['attempt'] = dict(id=attempt['id'],result=json.loads(attempt['result']),status=attempt['sync_status'],receipt=json.loads(attempt['sync_receipt']) if attempt.get('sync_receipt') else None) if attempt else None
    p['createdAt'] = session_row['created_at']
    return p


REVIEW_SQL = 'INSERT INTO study_reviews (id,topic,due_date,reason,method,status,last_evidence,next_step) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET topic=excluded.topic,due_date=excluded.due_date,reason=excluded.reason,method=excluded.method,status=excluded.status,last_evidence=excluded.last_evidence,next_step=excluded.next_step'


def review_query(r):
    return (REVIEW_SQL, (r['id'], r['topic'], r.get('date') or None, r.get('reason') or '', r.get('method') or 'Separate recall review', r['status'], r.get('lastEvidence') or None, r.get('nextStep') or ''))


class StudyService:
    def __init__(self, db, now=None):
        self.db = db
        self.now = now or (lambda: datetime.now(timezone.utc))

    def stamp(self):
        return self.now().isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    async def publish(self, payload):
        p = validate_session(payload)
        existing = await self.db.one('SELECT payload FROM study_sessions WHERE id=?',p['id'])
        if existing:
            if json.loads(existing['payload']) != p:
                raise StudyError('Existing published sessions are immutable.',409)
            return dict(id=p['id'],created=False)
        stored = json.dumps(p, ensure_ascii=False, separators=(',',':'))
        await self.db.execute('INSERT INTO study_sessions (id,date,payload,created_at) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING',p['id'],p['date'],stored,self.stamp())
        row = await self.db.one('SELECT * FROM study_sessions WHERE id=?',p['id'])
        if json.loads(row['payload']) != p:
            raise StudyError('Existing published sessions are immutable.',409)
        return dict(id=p['id'], created=True, questions=3)

    async def save_answers(self, p):
        if not isinstance(p, dict) or not text(p.get('sessionId'),100):
            raise StudyError('A session is required.')
        s = await self.db.one('SELECT * FROM study_sessions WHERE id=?',p['sessionId'])
        if not s:
            raise StudyError('Session not found.',404)
        attempt = await self.db.one('SELECT * FROM study_attempts WHERE session_id=?',p['sessionId'])
        if not attempt:
            stamp = self.stamp()
            result = grade(json.loads(s['payload']),p.get('answers'),stamp)
            await self.db.execute('INSERT INTO study_attempts (id,session_id,answers,result,submitted_at,sync_status) VALUES (?,?,?,?,?,?) ON CONFLICT(session_id) DO NOTHING',str(uuid4()),s['id'],json.dumps(p['answers']),json.dumps(result),stamp,'pending')
            attempt = await self.db.one('SELECT * FROM study_attempts WHERE session_id=?',s['id'])
        result = json.loads(attempt['result'])
        queries = []
        for q in result['questions']:
            reason = 'Incorrect first attempt' if not q['correct'] else 'Correct but uncertain' if q['confidence'] in ('unsure','guessed') else 'Spaced retention'
            queries.append(('INSERT INTO study_reviews (id,topic,due_date,reason,method,status,last_evidence,next_step) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',('attempt:'+attempt['id']+':'+q['questionId'],q['topic'],q['nextReview'],reason,'Separate application / recall','Planned',result['completionDate'],'Review '+q['objective']+'; interval is a study heuristic, not a mastery rating.')))
        await self.db.batch(queries)
        return view(s,attempt)

    async def performance(self):
        row = await self.db.one('SELECT * FROM study_state WHERE key=?','legacy')
        if not row:
            raise StudyError('Historical import has not been loaded yet.',503)
        d = json.loads(row['value'])
        d['source'].update(mode='database',liveAsOf=self.stamp())
        days = {r[0] for r in d['tabs']['Sessions'][1:] if r[2] == 'Verified' and r[5] == 'Yes'}
        attempts = await self.db.all('SELECT a.*,s.payload AS session_payload FROM study_attempts a JOIN study_sessions s ON a.session_id=s.id ORDER BY a.submitted_at')
        for a in attempts:
            r, s = json.loads(a['result']), json.loads(a['session_payload'])
            day = r['completionDate']
            d['tabs']['Sessions'].append([day,s['id'],'Verified','3',str(r['correct']),'No' if bonus(s) or day in days else 'Yes','; '.join(q['confidence'] for q in r['questions']),'site_attempt='+a['id']+'; kind='+('bonus' if bonus(s) else 'daily')])
            if not bonus(s):
                days.add(day)
            for q in r['questions']:
                original = next(x for x in s['questions'] if x['id'] == q['questionId'])
                note = 'series=CA2-New; attempt=1; difficulty='+q['difficulty']+'; level='+q['level']+'; site_session='+s['id']+'; site_attempt='+a['id']+'; objective='+q['objective']+'; '+original['stem'][:500]
                d['tabs']['Question Log'].append([day,s['id'],q['questionId'],q['domain'],q['topic'],q['choice'],q['key'],str(int(q['correct'])),q['confidence'],q['errorType'],note])
        reviews = await self.db.all('SELECT * FROM study_reviews ORDER BY due_date,id')
        d['tabs']['Review Queue'] = [['Review date','Topic','Reason','Method','Status','Last evidence','Result / next step']] + [[r['due_date'] or '',r['topic'],r['reason'],r['method'],r['status'],r['last_evidence'] or '',r['next_step']] for r in reviews]
        verified = [r for r in d['tabs']['Sessions'][1:] if r[2] == 'Verified']
        total, correct = sum(int(r[3]) for r in verified), sum(int(r[4]) for r in verified)
        for i,value in [(4,str(total)),(5,str(correct)),(6,f'{100*correct/total:.1f}%' if total else 'Not started'),(7,str(len(days)))]:
            d['tabs']['Dashboard'][i][1] = value
        return d

    async def public_data(self):
        sessions = await self.db.all('SELECT * FROM study_sessions ORDER BY date DESC LIMIT 365')
        attempts = {a['session_id']:a for a in await self.db.all('SELECT * FROM study_attempts ORDER BY submitted_at DESC LIMIT 365')}
        pipeline = await self.db.one('SELECT * FROM study_state WHERE key=?','pipeline')
        return dict(today=self.now().astimezone(EASTERN).date().isoformat(),sessions=[view(s,attempts.get(s['id'])) for s in sessions],pipeline=json.loads(pipeline['value']) if pipeline else None,performance=await self.performance(),reviews=await self.db.all('SELECT * FROM study_reviews ORDER BY due_date'),articles=await self.db.all('SELECT * FROM study_articles ORDER BY date DESC LIMIT 1000'))

    async def context(self):
        pending = await self.db.all("SELECT a.*,s.payload AS session_payload FROM study_attempts a JOIN study_sessions s ON a.session_id=s.id WHERE a.sync_status='pending' ORDER BY a.submitted_at LIMIT 100")
        sessions = await self.db.all('SELECT payload FROM study_sessions ORDER BY date DESC LIMIT 365')
        return dict(workflow=WORKFLOW,pending=[dict(id=a['id'],session=json.loads(a['session_payload']),result=json.loads(a['result']),answers=json.loads(a['answers'])) for a in pending],sessions=[json.loads(s['payload']) for s in sessions],performance=await self.performance(),reviews=await self.db.all('SELECT * FROM study_reviews ORDER BY due_date'),articles=await self.db.all('SELECT * FROM study_articles ORDER BY date DESC LIMIT 1000'))

    async def record_article(self, a):
        if not isinstance(a,dict) or not text(a.get('title'),500) or not text(a.get('url'),1000) or not a['url'].startswith('https://') or not valid_date(a.get('date')) or a.get('status') not in ('Prepared','Included','Emailed','Sent'):
            raise StudyError('Invalid article record.')
        doi = re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*','',str(a.get('doi') or '').strip().lower()) or None
        key = re.sub('[^a-z0-9]+',' ',a['title'].lower()).strip()
        old = await self.db.one('SELECT * FROM study_articles WHERE title_key=? OR (doi IS NOT NULL AND doi=?)',key,doi)
        if old:
            return dict(id=old['id'],duplicate=True)
        uid = str(uuid4())
        await self.db.execute('INSERT INTO study_articles (id,date,title,title_key,authors,journal,year,doi,url,topic,takeaway,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',uid,a['date'],a['title'],key,a.get('authors') or '',a.get('journal') or '',str(a.get('year') or ''),doi,a['url'],a.get('topic') or '',a.get('takeaway') or '',a['status'])
        saved = await self.db.one('SELECT * FROM study_articles WHERE title_key=? OR (doi IS NOT NULL AND doi=?)',key,doi)
        return dict(id=saved['id'],duplicate=saved['id']!=uid)

    async def action(self, action, p=None):
        if action == 'context': return await self.context()
        if action == 'publish_session': return await self.publish(p)
        if action == 'record_answers': return await self.save_answers(p)
        if action == 'record_article': return await self.record_article(p)
        if action == 'mark_reviewed':
            if not isinstance(p,dict) or not p.get('attemptId') or not text(p.get('summary'),5000):
                raise StudyError('Attempt id and planning summary required.')
            a = await self.db.one('SELECT id FROM study_attempts WHERE id=?',p['attemptId'])
            if not a: raise StudyError('Attempt not found.',404)
            receipt = dict(reviewedAt=self.stamp(),summary=p['summary'])
            await self.db.execute('UPDATE study_attempts SET sync_status=?,sync_receipt=? WHERE id=?','reviewed',json.dumps(receipt),p['attemptId'])
            return dict(id=p['attemptId'],reviewed=True)
        if action == 'plan_reviews':
            if not isinstance(p,list) or len(p)>50: raise StudyError('At most 50 review records per update.')
            for r in p:
                if not text(r.get('id'),180) or not text(r.get('topic'),300) or r.get('status') not in ('Planned','Completed','Backlog','Exposed') or r.get('date') and not valid_date(r['date']):
                    raise StudyError('Invalid review record.')
            if p: await self.db.batch([review_query(r) for r in p])
            return dict(saved=len(p))
        if action == 'heartbeat':
            if not isinstance(p,dict) or p.get('status') not in ('ok','error') or not text(p.get('message'),2000): raise StudyError('Invalid pipeline status.')
            value = dict(**p,checkedAt=self.stamp())
            await self.db.execute('INSERT INTO study_state (key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at','pipeline',json.dumps(value),value['checkedAt'])
            return dict(saved=True)
        raise StudyError('Unknown action.')
