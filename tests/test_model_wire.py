import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from backend.db import ROOT
from backend.main import create_app
from backend.model import INTERPRET, GENERATE, AUDIT

QUESTION = '你亲自核实过这个岗位吗？'
JUDGMENT = '群里转发不能证明招聘方获得了授权。'
REPLY = '我在校园群看到了这条消息，没亲自核实。'
HELLO = '你好。'
AUTH_QUESTION = '你能说明这次招聘的委托关系吗？'
AUTH_REPLY = '我目前无法出示可核实的企业招聘授权。'
TURNS = {
    HELLO: ([], '你好，有什么想了解的？', []),
    QUESTION: ([('verify_friend','K05')], REPLY, [{'focus':'K05','quote':'没亲自核实。'}]),
    JUDGMENT: ([('identify_gap','K01'),('weigh_sources','K01')], '明白，你想先找依据。', []),
    AUTH_QUESTION: ([('ask_employer','K01')], AUTH_REPLY, [{'focus':'K01','quote':AUTH_REPLY}]),
}

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
            if self.path != '/v1/chat/completions' or msg not in TURNS or self.headers.get('Authorization'):
                self.send_error(400); return
            calls.append((system,data))
            pairs, reply, disclosures = TURNS[msg]
            if system == INTERPRET:
                result = {'actions':[{'kind':k,'focus':f,'quote':msg,'source':'own'} for k,f in pairs]}
            elif system == GENERATE:
                result = {'body':reply}
            elif system == AUDIT:
                result = {'safe':True,'supported':list(range(len(data['candidates']))),'disclosures':disclosures,'registration_quote':None}
            else:
                self.send_error(400); return
            body = json.dumps({'choices':[{'message':{'role':'assistant','content':json.dumps(result,ensure_ascii=False)}}]},ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        th = threading.Thread(target=server.serve_forever,daemon=True); th.start()
        try: yield f'http://127.0.0.1:{server.server_port}/v1', calls
        finally: server.shutdown(); th.join()

@pytest.fixture
def wired_session(tmp_path, monkeypatch):
    db_url = f'sqlite:///{(tmp_path / "wire.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL',db_url)
    monkeypatch.setenv('OPENAI_API_KEY','')
    command.upgrade(Config(str(ROOT / 'alembic.ini')),'head')
    with wire_fixture() as (base,calls):
        monkeypatch.setenv('OPENAI_BASE_URL',base)
        with TestClient(create_app()) as client:
            s = client.post('/api/sessions').json(); path = '/api/sessions/'+s['id']; headers={'Authorization':'Bearer '+s['token']}
            yield client, path, headers, calls


def test_two_turns_through_compatible_http_contract(wired_session):
    client, path, headers, calls = wired_session
    for msg in [QUESTION,JUDGMENT]:
        res = client.post(path+'/turns',headers=headers,json={'role':'wang','text':msg,'request_id':str(uuid4())})
        assert 'event: done' in res.text and res.text.count('event: progress') == 3
    report = client.post(path+'/finish',headers=headers,json={'kind':'decision','choice':'verify','reason':JUDGMENT,'cited':[1,2]}).json()
    assert len(calls) == 6
    assert [role for role,_ in calls] == [INTERPRET,GENERATE,AUDIT]*2
    assert set(calls[1][1]['permitted_facts']) == {'K05'}
    assert [e['focus'] for e in report['disclosures']] == ['K05']
    assert report['dimensions'][0]['evidence'][0]['quote'] == JUDGMENT


def test_model_receives_only_the_active_role_card(wired_session):
    client, path, headers, calls = wired_session
    profiles = {
        'lin': ('林悦', ('澄海科技','3,000–4,000','技术面试'), ('陈浩','王宇','3,500–4,500')),
        'chen': ('陈浩', ('招聘顾问','3,500–4,500','初步筛选'), ('林悦','王宇','澄海科技','3,000–4,000','无法出示')),
        'wang': ('王宇', ('大学朋友','校园求职群'), ('林悦','陈浩','澄海科技','3,000–4,000','3,500–4,500','没有亲自')),
    }
    for role, (name, expected, excluded) in profiles.items():
        res = client.post(path+'/turns',headers=headers,json={'role':role,'text':HELLO,'request_id':str(uuid4())})
        assert 'event: done' in res.text
        analysis, generation, audit = (payload for _,payload in calls[-3:])
        assert analysis == {'contact':name, 'private_history':[], 'current_user':HELLO}
        assert generation['character']['name'] == name and 'Python 后端' in generation['scene']
        assert generation['private_history'] == [] and generation['permitted_facts'] == {}
        assert generation['allow_invitation'] is False
        assert all(audit[key] == value for key,value in generation.items())
        visible = json.dumps(generation, ensure_ascii=False)
        assert all(term in visible for term in expected)
        assert not any(term in visible for term in (*excluded, '栖禾', '内容运营', '隐藏设定'))


def test_employer_question_unlocks_only_the_consultants_authorization_clue(wired_session):
    client, path, headers, calls = wired_session
    for role, msg in [('chen',AUTH_QUESTION), ('lin',HELLO)]:
        res = client.post(path+'/turns',headers=headers,json={'role':role,'text':msg,'request_id':str(uuid4())})
        assert 'event: done' in res.text
    for _,payload in calls[1:3]:
        assert set(payload['permitted_facts']) == {'K01'}
        assert '委托关系' in payload['permitted_facts']['K01'] and not payload['allow_invitation']
    for _,payload in calls[4:6]:
        assert payload['permitted_facts'] == {} and payload['private_history'] == []
