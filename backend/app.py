"""FastAPI HTTP contract. Every route requires a server-side gateway secret.

The existing owner-private Sites gate authenticates the person. This service
never accepts a user id header as authentication without the shared secret.
"""
import hmac
import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .service import StudyService, StudyError, WORKFLOW
from .storage import D1Store
from .d1_http import D1HTTPStore

HEADERS = {'cache-control':'private, no-store, max-age=0','x-content-type-options':'nosniff'}


def create_app(store=None, token=None, now=None):
    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def private_gateway(request, call_next):
        env = request.scope.get('env')
        expected = token or getattr(env,'GATEWAY_TOKEN','') or os.environ.get('GATEWAY_TOKEN','')
        actual = request.headers.get('x-ite-gateway-token','')
        if not expected or not hmac.compare_digest(str(expected).encode('utf-8'), actual.encode('utf-8')):
            return JSONResponse({'error':'Private study backend.'},status_code=401,headers=HEADERS)
        if request.method == 'POST':
            origin = request.headers.get('origin')
            allowed = str(getattr(env,'SITE_ORIGIN',None) or os.environ.get('SITE_ORIGIN','https://vincent-ite-study-dashboard.grittypeach1026.chatgpt.site'))
            if origin and origin != allowed or request.headers.get('sec-fetch-site') == 'cross-site':
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
            return JSONResponse({'error':'Storage request failed. Your existing records are preserved.'},status_code=500,headers=HEADERS)
        response.headers.update(HEADERS)
        return response

    @app.exception_handler(StudyError)
    async def study_error(request, error):
        return JSONResponse({'error':str(error)},status_code=error.status,headers=HEADERS)

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
        session_id = ('CA2-Bonus ' if kind == 'bonus' else 'CA2-New ') + today
        existing = await request.state.study.db.one('SELECT id FROM study_sessions WHERE id=?',session_id)
        if existing:
            return {'status':'exists','sessionId':session_id}
        context = await build_authoring_context(request.state.study.db,today=today,kind=kind)
        draft = await draft_session(context,kind=kind)
        session = prepare_session(draft,today=today,kind=kind)
        # Draft-only until references and answer keys can be independently verified.
        return {'status':'requires_verification','session':session}

    @app.post('/api/submit')
    async def submit(request:Request):
        if not request.headers.get('oai-authenticated-user-id'):
            raise StudyError('Sign in to submit your answers.',401)
        return await request.state.study.save_answers(await body(request))

    @app.post('/api/agent')
    async def agent(request:Request):
        p = await body(request)
        return await request.state.study.action(p.get('action'),p.get('payload'))

    return app


app = create_app()
