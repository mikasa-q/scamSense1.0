import os
from pathlib import Path
import subprocess
import threading

from alembic import command
from alembic.config import Config
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

from backend.db import ROOT
from backend.main import create_app
from backend.model import INTERPRET, K05_INTERPRET
from test_model_wire import COMBINED, CORRECTION, HELLO, INTEREST, REOPEN, SENT_THEN_REFUSED, wire_fixture


def test_mobile_registration(tmp_path, monkeypatch):
    browser = os.environ['SCAMSENSE_TEST_BROWSER']
    dev_url = os.getenv('SCAMSENSE_TEST_DEV_URL')
    assert dev_url or (ROOT / 'frontend/dist/index.html').is_file(), 'Build the frontend before running the browser test.'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', f'sqlite:///{(tmp_path / "mobile.db").as_posix()}')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    result, done = {}, threading.Event()
    routes = APIRouter(prefix='/api/test-mobile')

    @routes.get('/', response_class=HTMLResponse)
    def phone():
        return ('<!doctype html><meta charset="utf-8"><title>登记回归 · 390 × 844</title>'
                '<iframe title="手机视口" width="390" height="844" style="border:0" src="/"></iframe>'
                '<output></output><script type="module" src="./flow.js"></script>')

    @routes.get('/flow.js')
    def script():
        return FileResponse(Path(__file__).with_suffix('.js'), media_type='text/javascript')

    @routes.post('/result')
    def finished(outcome: dict):
        result.update(outcome)
        done.set()

    with wire_fixture() as (base, calls):
        monkeypatch.setenv('OPENAI_BASE_URL', base)
        app = create_app()
        app.router.routes[:0] = routes.routes  # Test routes must precede the built frontend's static mount.
        config = uvicorn.Config(app, host='127.0.0.1', port=8765 if dev_url else 0, log_level='warning')
        server = uvicorn.Server(config)
        with config.bind_socket() as sock:
            url = dev_url or f'http://127.0.0.1:{sock.getsockname()[1]}'
            thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]})
            thread.start()
            try:
                with subprocess.Popen([browser, '--headless', '--disable-gpu', '--no-first-run',
                                       f'--user-data-dir={tmp_path / "profile"}', url + '/api/test-mobile/'],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
                    try:
                        assert done.wait(90), 'Browser did not report a result.'
                        assert result.get('ok'), result.get('error')
                    finally:
                        process.terminate()
            finally:
                server.should_exit = True
                thread.join()
    assert [(step, d['current_user']) for step, d in calls if step in (K05_INTERPRET, INTERPRET)] == [
        (K05_INTERPRET, HELLO), (INTERPRET, INTEREST), (INTERPRET, COMBINED), (INTERPRET, CORRECTION),
        (INTERPRET, SENT_THEN_REFUSED), (INTERPRET, '我不参与预登记。'), (INTERPRET, REOPEN)]
