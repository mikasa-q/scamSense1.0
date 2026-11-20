import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import os
from typing import Annotated, Literal
from uuid import UUID
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import sessionmaker
from . import training
from .db import ROOT, database_url, engine_for
from .model import CompatibleModel
from .policy import Role, sensitive

class TurnInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID
    role: Role
    text: str = Field(min_length=1, max_length=600)

class EndInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    kind: Literal['early', 'decision']
    choice: Literal['verify','leave','continue','necessary_only'] | None = None
    reason: str = Field(default='', max_length=600)
    cited: list[int] = Field(default_factory=list, max_length=6)

    @model_validator(mode='after')
    def check_ending(self):
        if self.kind == 'early' and (self.choice or self.reason or self.cited):
            raise ValueError('early is not a decision')
        if self.kind == 'decision' and self.choice is None:
            raise ValueError('decision requires choice')
        return self

def check_text(text):
    if sensitive(text):
        raise HTTPException(422, '内容疑似包含真实联系方式、证件、卡号或住址。请改用「虚构资料 A」等占位文字。')

def sse(kind, data):
    return 'event: ' + kind + '\ndata: ' + json.dumps(data, ensure_ascii=False, separators=(',',':')) + '\n\n'

def create_app(url=None, model=None):
    engine = engine_for(url or database_url())
    factory = sessionmaker(engine, expire_on_commit=False)
    model = model if model is not None else CompatibleModel()
    tasks = set()

    @asynccontextmanager
    async def lifespan(_):
        yield
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        engine.dispose()

    app = FastAPI(title='ScamSense 训练室', version='0.1.0', lifespan=lifespan)
    app.state.factory, app.state.engine = factory, engine
    if origin := os.getenv('SCAMSENSE_WEB_ORIGIN'):
        app.add_middleware(CORSMiddleware, allow_origins=[origin.rstrip('/')], allow_methods=['GET','POST'], allow_headers=['Content-Type','Authorization'])

    @app.exception_handler(RequestValidationError)
    async def reject_invalid(_, __):
        return JSONResponse(status_code=422, content={'detail':'输入格式不符，请检查内容、字数或选择后重试。'})

    @app.middleware('http')
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def owned(sid: str, authorization: Annotated[str | None, Header()] = None):
        token = (authorization or '').removeprefix('Bearer ')
        if not authorization or token == authorization:
            raise HTTPException(401, '需要本场训练的访问凭据。')
        training.check_access(factory, sid, token)

    @app.get('/api/health')
    def health():
        return {'service':'ScamSense', 'model_configured':model.configured}

    @app.post('/api/sessions', status_code=201)
    def new_training():
        return training.create(factory)

    @app.get('/api/sessions/{sid}', dependencies=[Depends(owned)])
    def get_training(sid: str):
        return training.snapshot(factory, sid)

    @app.post('/api/sessions/{sid}/turns', dependencies=[Depends(owned)])
    async def turn(sid: str, data: TurnInput):
        check_text(data.text)
        reservation = training.reserve(factory, sid, str(data.request_id), data.role, data.text, model.configured)
        queue = asyncio.Queue()
        if reservation:
            async def work():
                try:
                    ok = await training.run_turn(factory, model, sid, reservation, data.role, data.text, lambda status:queue.put_nowait(('progress',{'text':status})))
                    queue.put_nowait(('done', {'cached':False}) if ok else ('error', {'detail':'本轮模型调用或事实校验未通过，没有写入对话。可原样重试。'}))
                except Exception:
                    queue.put_nowait(('error', {'detail':'本轮状态暂不可读，请刷新核实后重试。'}))
            task = asyncio.create_task(work())
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        async def events() -> AsyncIterator[str]:
            if not reservation:
                yield sse('done', {'cached':True, 'session':training.snapshot(factory, sid)})
                return
            while True:
                try:
                    kind, obj = await asyncio.wait_for(queue.get(), timeout=12)
                except TimeoutError:
                    yield ': keepalive\n\n'
                    continue
                if kind == 'done':
                    obj['session'] = training.snapshot(factory, sid)
                yield sse(kind, obj)
                if kind != 'progress':
                    break
        return StreamingResponse(events(), media_type='text/event-stream', headers={'X-Accel-Buffering':'no','Cache-Control':'no-store'})

    @app.post('/api/sessions/{sid}/finish', dependencies=[Depends(owned)])
    def end(sid: str, data: EndInput):
        check_text(data.reason)
        return training.finish(factory, sid, data.kind, data.choice, data.reason, list(dict.fromkeys(data.cited)))

    dist = ROOT / 'frontend' / 'dist'
    if dist.is_dir():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app
