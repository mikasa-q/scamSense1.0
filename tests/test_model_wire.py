import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from backend.db import ROOT
from backend.main import create_app
from backend.model import INTERPRET, GENERATE, AUDIT

QUESTION = '你亲自核实过这个岗位吗？'
JUDGMENT = '群里转发不能证明招聘方获得了授权。'
REPLY = '我在校园群看到了这条消息，没亲自核实。'

@contextmanager
def wire_fixture():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            system = request['messages'][0]['content']
            data = json.loads(request['messages'][1]['content'])
            msg = data['current_user']
            if self.path != '/v1/chat/completions' or msg not in [QUESTION,JUDGMENT] or self.headers.get('Authorization'):
                self.send_error(400); return
            calls.append((system,data))
            if system == INTERPRET:
                pairs = [('verify_friend','K05')] if msg == QUESTION else [('identify_gap','K01'),('weigh_sources','K01')]
                result = {'actions':[{'kind':k,'focus':f,'quote':msg,'source':'own'} for k,f in pairs]}
            elif system == GENERATE:
                result = {'body':REPLY if msg == QUESTION else '明白，你想先找依据。'}
            elif system == AUDIT:
                result = {'safe':True,'supported':list(range(len(data['candidates']))),'disclosures':[{'focus':'K05','quote':'没亲自核实。'}] if msg == QUESTION else [],'registration_quote':None}
            else:
                self.send_error(400); return
            body = json.dumps({'choices':[{'message':{'role':'assistant','content':json.dumps(result,ensure_ascii=False)}}]},ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        th = threading.Thread(target=server.serve_forever,daemon=True); th.start()
        try: yield f'http://127.0.0.1:{server.server_port}/v1', calls
        finally: server.shutdown(); th.join()

def test_two_turns_through_compatible_http_contract(tmp_path, monkeypatch):
    db_url = f'sqlite:///{(tmp_path / "wire.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL',db_url)
    monkeypatch.setenv('OPENAI_API_KEY','')
    command.upgrade(Config(str(ROOT / 'alembic.ini')),'head')
    with wire_fixture() as (base,calls):
        monkeypatch.setenv('OPENAI_BASE_URL',base)
        with TestClient(create_app()) as client:
            s = client.post('/api/sessions').json(); path = '/api/sessions/'+s['id']; headers={'Authorization':'Bearer '+s['token']}
            for msg in [QUESTION,JUDGMENT]:
                res = client.post(path+'/turns',headers=headers,json={'role':'wang','text':msg,'request_id':str(uuid4())})
                assert 'event: done' in res.text and res.text.count('event: progress') == 3
            report = client.post(path+'/finish',headers=headers,json={'kind':'decision','choice':'verify','reason':JUDGMENT,'cited':[1,2]}).json()
        assert len(calls) == 6
        assert [role for role,_ in calls] == [INTERPRET,GENERATE,AUDIT]*2
        assert [e['focus'] for e in report['disclosures']] == ['K05']
        assert report['dimensions'][0]['evidence'][0]['quote'] == JUDGMENT
