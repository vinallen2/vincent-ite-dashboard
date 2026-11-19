"""Reconstruct an exact, deduplicated snapshot from authorized API readbacks.

Local .runtime files are private and ignored by Git. Never recover Nov 14's
chat-only session. Never infer missing answer or question content.
"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.local import SQLiteStore
from backend.service import StudyService

EXCLUDED_DATE = '2026-11-14'
TABLES = ('study_sessions','study_attempts','study_reviews','study_articles','study_state')


def prepare(context, public):
    base = json.loads(json.dumps(context['performance']))
    base['tabs']['Sessions'] = [r for i,r in enumerate(base['tabs']['Sessions']) if i == 0 or (r[0] != EXCLUDED_DATE and not any('site_attempt=' in str(v) for v in r))]
    base['tabs']['Question Log'] = [r for i,r in enumerate(base['tabs']['Question Log']) if i == 0 or (r[0] != EXCLUDED_DATE and not any('site_session=' in str(v) for v in r))]
    # Dashboard's derived counters are recalculated by the service. Reviews and
    # articles use their authoritative tables, not the cached legacy projection.
    rows = {t:[] for t in TABLES}
    rows['study_state'].append(dict(key='legacy',value=json.dumps(base),updated_at=base['source']['importedAt']))
    if public.get('pipeline'):
        p = public['pipeline']
        rows['study_state'].append(dict(key='pipeline',value=json.dumps(p),updated_at=p['checkedAt']))
    by_id = {s['id']:s for s in public['sessions']}
    for s in context['sessions']:
        if s['date'] == EXCLUDED_DATE: continue
        existing = by_id[s['id']]
        rows['study_sessions'].append(dict(id=s['id'],date=s['date'],payload=json.dumps(s,ensure_ascii=False,separators=(',',':')),created_at=existing['createdAt']))
        a = existing.get('attempt')
        if a:
            # Full saved result includes the exact original submitted choices.
            result = a['result']
            pending = next((p for p in context['pending'] if p['id']==a['id']),None)
            answers = pending['answers'] if pending else [dict(questionId=q['questionId'],choice=q['choice'],confidence='' if q['confidence']=='Not provided' else q['confidence']) for q in result['questions']]
            rows['study_attempts'].append(dict(id=a['id'],session_id=s['id'],answers=json.dumps(answers),result=json.dumps(result),submitted_at=result['submittedAt'],sync_status=a['status'],sync_receipt=json.dumps(a['receipt']) if a.get('receipt') else None))
    allowed_ids = {a['id'] for a in rows['study_attempts']}
    for r in context['reviews']:
        if r['id'].startswith('attempt:') and r['id'].split(':')[1] not in allowed_ids: continue
        rows['study_reviews'].append(r)
    rows['study_articles'] = [a for a in context['articles'] if a['date'] != EXCLUDED_DATE]
    return rows


def batches(rows):
    result = []
    for table in TABLES:
        for row in rows[table]:
            columns = list(row)
            result.append(dict(sql=f'INSERT INTO {table} ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+') ON CONFLICT DO NOTHING',params=[row[c] for c in columns]))
    return result


async def main():
    context = json.loads((ROOT/'.runtime/context-export.json').read_text())
    public = json.loads((ROOT/'.runtime/public-export.json').read_text())
    rows = prepare(context,public)
    db = SQLiteStore()
    db.conn.executescript((ROOT/'migrations/0001_initial.sql').read_text())
    queries = batches(rows)
    await db.batch([(q['sql'],q['params']) for q in queries])
    # Replay verifies idempotent migration without changing first attempts.
    await db.batch([(q['sql'],q['params']) for q in queries])
    service = StudyService(db)
    migrated = await service.public_data()
    expected = public['performance']['tabs']
    actual = migrated['performance']['tabs']
    for tab in ('Sessions','Question Log','Review Queue'):
        assert actual[tab] == expected[tab], f'{tab} changed during reconciliation'
    assert sorted(migrated['sessions'],key=lambda s:s['id']) == sorted(public['sessions'],key=lambda s:s['id']), 'Saved session or attempt changed'
    assert migrated['articles'] == public['articles'], 'Article changed'
    metric = actual['Dashboard']
    report = dict(counts={t:len(rows[t]) for t in TABLES},verified_questions=int(metric[4][1]),correct=int(metric[5][1]),accuracy=metric[6][1],completed_daily_dates=int(metric[7][1]),excluded_date=EXCLUDED_DATE,excluded_session_count=sum(s['date']==EXCLUDED_DATE for s in context['sessions']),reconciliation='exact sessions, answers, first-attempt IDs, performance, review queue, articles; idempotent replay passed')
    (ROOT/'.runtime/migration-rows.json').write_text(json.dumps(rows))
    (ROOT/'.runtime/import-batch.json').write_text(json.dumps(dict(batch=queries)))
    report['snapshot_sha256'] = hashlib.sha256((ROOT/'.runtime/migration-rows.json').read_bytes()).hexdigest()
    (ROOT/'.runtime/migration-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == '__main__': asyncio.run(main())
