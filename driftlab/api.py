from contextlib import asynccontextmanager
import json
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import ROOT
from .database import configured
from .generate import generate
from .jobs import Manager
from .model import fields


def create_app(history_root=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.manager = Manager(history_root)
        try:
            yield
        finally:
            app.state.manager.close()

    app = FastAPI(title='DB Drift Detective', version='0.1.0', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        if request.method == 'POST':
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': 'Cross-origin writes are disabled'}, status_code=403)
            length = request.headers.get('content-length', '0')
            if not length.isdigit() or int(length) > 2 * 1024 * 1024:
                return JSONResponse({'detail': 'Request body exceeds 2 MiB'}, status_code=413)
        return await call_next(request)

    def manager():
        return app.state.manager

    def lookup(identifier):
        try:
            return manager().get(identifier)
        except KeyError:
            raise HTTPException(404, 'Comparison not found') from None

    def submit(case, kind):
        try:
            return manager().submit(case, kind)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from None
        except RuntimeError as error:
            raise HTTPException(429, str(error)) from None

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'postgres_configured': configured(), 'project': str(ROOT)}

    @app.get('/api/cases')
    def cases():
        return [{'id': file.stem, 'case': json.loads(file.read_text(encoding='utf-8'))}
                for file in sorted((ROOT / 'cases').glob('*.json'))]

    @app.post('/api/generate')
    def generate_case(options: dict):
        try:
            fields(options, ('family', 'rows', 'seed', 'fixed'))
            if type(options.get('fixed', False)) is not bool:
                raise ValueError('fixed must be boolean')
            return generate(options.get('family', 'null_order'), options.get('rows', 100),
                            options.get('seed', 7), options.get('fixed', False))
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/api/jobs')
    def jobs():
        return manager().list()

    @app.post('/api/jobs', status_code=202)
    def create_job(body: dict):
        try:
            fields(body, ('case', 'kind'), ('case',))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return submit(body['case'], body.get('kind', 'compare'))

    @app.get('/api/jobs/{identifier}')
    def detail(identifier: str):
        return lookup(identifier)

    @app.post('/api/jobs/{identifier}/replay', status_code=202)
    def replay(identifier: str):
        return submit(lookup(identifier)['case'], 'compare')

    @app.post('/api/jobs/{identifier}/reduce', status_code=202)
    def reduce(identifier: str):
        item = lookup(identifier)
        if item['status'] != 'drift':
            raise HTTPException(409, 'Choose a comparison with a drift finding')
        return submit(item['case'], 'reduce')

    @app.post('/api/jobs/{identifier}/cancel')
    def cancel(identifier: str):
        lookup(identifier)
        try:
            return manager().cancel(identifier)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.get('/api/jobs/{identifier}/bundle')
    def bundle(identifier: str):
        item = lookup(identifier)
        if 'bundle' not in item:
            raise HTTPException(409, 'Bundle is not ready')
        return FileResponse(item['bundle'], filename='drift-reproduction-' + item['id'] + '.zip', media_type='application/zip')

    app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'web' / 'index.html')

    return app
