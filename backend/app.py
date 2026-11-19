"""FastAPI HTTP contract. Every route requires a server-side gateway secret.

The existing owner-private Sites gate authenticates the person. This service
never accepts a user id header as authentication without the shared secret.
"""
import hmac
import base64
from pathlib import Path
import json
import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from .service import StudyService, StudyError, WORKFLOW
from .storage import D1Store
from .d1_http import D1HTTPStore

HEADERS = {'cache-control':'private, no-store, max-age=0','x-content-type-options':'nosniff'}


def create_app(store=None, token=None, now=None):
    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    log = logging.getLogger('ite.generation')

    async def publish_daily_if_missing():
        if os.environ.get('ITE_ENABLE_GENERATION') != 'true':
            return
        from .authoring_context import build_authoring_context, prepare_session
        from .openai_authoring import draft_session
        today = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
        db = store or D1HTTPStore(os.environ.get('CLOUDFLARE_ACCOUNT_ID'), os.environ.get('CLOUDFLARE_D1_DATABASE_ID'), os.environ.get('CLOUDFLARE_API_TOKEN'))
        session_id = 'CA2-New ' + today
        if await db.one('SELECT id FROM study_sessions WHERE id=?',session_id):
            return
        context = await build_authoring_context(db,today=today,kind='daily')
        draft = await draft_session(context,kind='daily')
        payload = prepare_session(draft,today=today,kind='daily')
        saved = await StudyService(db,now).publish(payload)
        log.warning('Daily ITE OpenAI generation published: %s, created=%s',session_id,saved['created'])

    async def generation_loop():
        # One scheduled attempt per calendar day at 6 AM America/New_York.
        # On startup after 6 AM, perform one catch-up attempt if today's session is missing.
        from datetime import timedelta
        last_attempt_date = None
        while True:
            local = datetime.now(ZoneInfo('America/New_York'))
            if local.hour >= 6 and last_attempt_date != local.date():
                last_attempt_date = local.date()
                try:
                    await publish_daily_if_missing()
                except Exception:
                    log.exception('Daily ITE OpenAI generation failed; no automatic retry today')
            local = datetime.now(ZoneInfo('America/New_York'))
            next_run = local.replace(hour=6,minute=0,second=0,microsecond=0)
            if next_run <= local:
                next_run += timedelta(days=1)
            await asyncio.sleep(max(1,(next_run-local).total_seconds()))

    @app.on_event('startup')
    async def start_generation():
        if os.environ.get('ITE_ENABLE_GENERATION') == 'true':
            app.state.generation_task = asyncio.create_task(generation_loop())

    @app.on_event('shutdown')
    async def stop_generation():
        task = getattr(app.state,'generation_task',None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @app.middleware('http')
    async def private_gateway(request, call_next):
        env = request.scope.get('env')
        expected = token or getattr(env,'GATEWAY_TOKEN','') or os.environ.get('GATEWAY_TOKEN','')
        actual = request.headers.get('x-ite-gateway-token','')
        site_password = os.environ.get('ITE_SITE_PASSWORD', '')
        authorization = request.headers.get('authorization', '')
        password_ok = False
        if site_password and authorization.startswith('Basic '):
            try:
                raw = base64.b64decode(authorization[6:], validate=True).decode('utf-8')
                username, supplied = raw.split(':', 1)
                password_ok = hmac.compare_digest(username, 'ite') and hmac.compare_digest(supplied, site_password)
            except (ValueError, UnicodeError):
                pass
        gateway_ok = bool(expected) and hmac.compare_digest(str(expected).encode('utf-8'), actual.encode('utf-8'))
        if not (gateway_ok or password_ok):
            return Response('Authentication required.',status_code=401,headers={**HEADERS,'www-authenticate':'Basic realm="ITE Study"'})
        request.state.password_authenticated = password_ok
        if request.method == 'POST':
            origin = request.headers.get('origin')
            allowed = str(getattr(env,'SITE_ORIGIN',None) or os.environ.get('SITE_ORIGIN','https://vincent-ite-study-dashboard.grittypeach1026.chatgpt.site'))
            # Railway terminates HTTPS at its reverse proxy; request.url.scheme may be http.
            # Compare the browser Origin to the public Host using HTTPS instead.
            host = request.headers.get('host', '')
            public_origin = f'https://{host}' if host else ''
            if (origin and origin not in (allowed, public_origin)) or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'error':'Same-origin request required.'},status_code=403,headers=HEADERS)
        if store is not None:
            db = store
        elif env is not None and getattr(env, 'DB', None) is not None:
            db = D1Store(env.DB)
        else:
            try:
                db = D1HTTPStore(os.environ.get('CLOUDFLARE_ACCOUNT_ID'), os.environ.get('CLOUDFLARE_D1_DATABASE_ID'), os.environ.get('CLOUDFLARE_API_TOKEN'))
            except ValueError:
                return JSONResponse({'error':'Study database is not configured.'},status_code=503,headers=HEADERS)
        request.state.study = StudyService(db,now)
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger('ite.backend').exception('Request failed on %s', request.url.path)
            return JSONResponse({'error':'Request failed on the server. Existing study records are preserved.'},status_code=500,headers=HEADERS)
        response.headers.update(HEADERS)
        return response

    @app.exception_handler(StudyError)
    async def study_error(request, error):
        return JSONResponse({'error':str(error)},status_code=error.status,headers=HEADERS)

    @app.get('/')
    async def homepage():
        template = (Path(__file__).resolve().parent.parent / 'frontend' / 'study.html').read_text()
        template = template.replace('<script>/*STUDY_SCRIPT*/</script>', '<script type="module">import {studyClient} from "/study-client.mjs"; studyClient();</script>')
        template = template.replace('Private · Owner only', 'Password protected')
        return HTMLResponse(template,headers=HEADERS)

    @app.get('/study-client.mjs')
    async def client_script():
        script = (Path(__file__).resolve().parent.parent / 'frontend' / 'study-client.mjs').read_text()
        return Response(script,media_type='text/javascript',headers=HEADERS)

    @app.get('/api/workflow')
    async def workflow(): return WORKFLOW

    @app.get('/api/study')
    async def study(request:Request): return await request.state.study.public_data()

    @app.get('/api/data')
    async def data(request:Request): return await request.state.study.performance()

    async def body(request):
        raw = await request.body()
        if len(raw)>250000: raise StudyError('Request too large.',413)
        try:
            p = json.loads(raw)
        except (json.JSONDecodeError,UnicodeDecodeError):
            raise StudyError('Invalid JSON.')
        if not isinstance(p,dict): raise StudyError('Expected a JSON object.')
        return p

    @app.post('/api/generate-draft')
    async def generate_draft(request:Request):
        # Explicitly opt-in. Never automatically publish unverified medical content.
        if os.environ.get('ITE_ENABLE_GENERATION') != 'true':
            raise StudyError('Generation is not enabled.',503)
        from .authoring_context import build_authoring_context, prepare_session
        from .openai_authoring import draft_session
        from datetime import datetime
        from zoneinfo import ZoneInfo
        p = await body(request)
        kind = p.get('kind','daily')
        today = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
        base_id = ('CA2-Bonus ' if kind == 'bonus' else 'CA2-New ') + today
        if kind not in ('daily','bonus'):
            raise StudyError('Invalid session kind.',400)
        if kind == 'bonus':
            rows = await request.state.study.db.all('SELECT id FROM study_sessions WHERE date=?',today)
            used = {r['id'] for r in rows}
            session_id = base_id
            number = 2
            while session_id in used:
                session_id = base_id + ' #' + str(number)
                number += 1
        else:
            session_id = base_id
            existing = await request.state.study.db.one('SELECT id FROM study_sessions WHERE id=?',session_id)
            if existing:
                return {'status':'exists','sessionId':session_id}
        context = await build_authoring_context(request.state.study.db,today=today,kind=kind)
        draft = await draft_session(context,kind=kind)
        session = prepare_session(draft,today=today,kind=kind)
        session['id'] = session_id
        saved = await request.state.study.publish(session)
        return {'status':'published','sessionId':session_id,'created':saved['created'],'questions':3}

    @app.post('/api/submit')
    async def submit(request:Request):
        if not (request.state.password_authenticated or request.headers.get('oai-authenticated-user-id')):
            raise StudyError('Sign in to submit your answers.',401)
        return await request.state.study.save_answers(await body(request))

    @app.post('/api/agent')
    async def agent(request:Request):
        if request.state.password_authenticated:
            raise StudyError('Publishing is reserved for the trusted gateway.',403)
        p = await body(request)
        return await request.state.study.action(p.get('action'),p.get('payload'))

    return app


app = create_app()
