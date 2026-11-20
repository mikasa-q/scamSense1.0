import asyncio
import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from backend.db import ROOT
from backend.main import create_app
from backend.model import CompatibleModel, K05_INTERPRET, GENERATE, K05_AUDIT
from backend.policy import Action, FACTS, Reply, k05_parts, validate_reply

QUESTION = '这机会你亲自问过招聘方吗？'
JUDGMENT = '群里转发不能证明招聘方获得了授权。'
REPLY = '没有，群里看到的。'

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
            if system == K05_INTERPRET:
                pairs = [('verify_friend','K05')] if msg == QUESTION else [('identify_gap','K01'),('weigh_sources','K01')]
                result = {'actions':[{'kind':k,'focus':f,'quote':msg,'source':'own'} for k,f in pairs]}
            elif system == GENERATE:
                result = {'body':REPLY if msg == QUESTION else '明白，你想先找依据。'}
            elif system == K05_AUDIT:
                kinds = ['self_denies_job_check','origin'] if msg == QUESTION else ['other','other']
                finding = [{'part_id':i, 'kind':kind} for i, kind in enumerate(kinds)]
                result = {'safe':True,'supported':list(range(len(data['candidates']))),'disclosures':[],'registration_quote':None,'k05':finding}
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
        assert [prompt for prompt,_ in calls] == [K05_INTERPRET,GENERATE,K05_AUDIT]*2
        assert calls[2][1]['current_user'] == QUESTION and calls[2][1]['reply'] == REPLY
        assert calls[2][1]['reply_parts'] == [{'part_id':0, 'text':'没有，'}, {'part_id':1, 'text':'群里看到的。'}]
        assert calls[5][1]['private_history'] == [{'speaker':'user','text':QUESTION}, {'speaker':'assistant','text':REPLY}]
        ref, = report['disclosures']
        assert (ref['focus'],ref['speaker'],ref['message_id'],ref['quote']) == ('K05','assistant',2,REPLY)
        risk, = report['dimensions'][0]['evidence']
        assert (risk['speaker'],risk['message_id'],risk['quote']) == ('user',3,JUDGMENT)

@pytest.mark.skipif(os.getenv('SCAMSENSE_TEST_LIVE_K05') != '1', reason='requires an explicitly enabled real model')
@pytest.mark.parametrize(('question','reply','evidence'), [
    (QUESTION, '没有，群里看到的。', ('没有',)),
    (QUESTION, '没有，我只看了群转发，没跟招聘方打过交道。', ('没有', '没跟招聘方打过交道')),
    ('我在整理校园招聘的信息渠道，你是在校园群、公众号还是学校网站看到这条消息的？',
     '我在校园群看到的，当时觉得挺有意思的，但没去查真伪。', ('没去查真伪',)),
    ('这条消息是你从学校官网看到的吗？', '没有，群里看到的。', ()),
    ('你从哪看到的？', '校园群里有人转发过。', ()),
    ('你从哪看到的？', '我是在群里看到的，没问清楚源头。', ()),
    (QUESTION, '发给我的同学没亲自核实。', ()),
    (QUESTION, '我记不清当时问过没有。', ()),
], ids=['elliptical', 'natural', 'mixed', 'elliptical-origin', 'source', 'forward-origin', 'other-person', 'uncertain'])
def test_live_k05_judgment(question, reply, evidence):
    action = Action(kind='verify_friend', focus='K05', quote=question, source='own')
    audit = asyncio.run(CompatibleModel().audit('wang', [], question, FACTS['wang'], False, [action], reply))
    assert audit.supported == [0] and audit.k05 is not None
    _, _, disclosed, _ = validate_reply(Reply(body=reply), audit, [action], FACTS['wang'], set(), False, role='wang')
    assert disclosed == ({'K05':reply} if evidence else {})
    parts = k05_parts(reply)
    denied = [parts[claim.part_id] for claim in audit.k05 if claim.kind == 'self_denies_job_check']
    assert all(any(fragment in part for fragment in evidence) for part in denied)
