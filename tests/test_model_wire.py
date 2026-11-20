import asyncio
import json
import os
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
from backend.model import AUDIT, CHEN_AUDIT, CHEN_GENERATE, CHEN_INTERPRET, GENERATE, INTERPRET, K05_ACTIONS, K05_AUDIT, K05_INTERPRET, CompatibleModel
from backend.policy import Action, FACTS, Reply, k05_parts, validate_reply

QUESTION = '这机会你亲自问过招聘方吗？'
JUDGMENT = '群里转发不能证明招聘方获得了授权。'
REPLY = '没有，群里看到的。'
MEMORY_QUESTION = '你还记得当时有没有问过招聘方吗？'
SOURCE_QUESTION = '你从哪看到的？'
HELLO = '你好。'
AUTH_QUESTION = '你能说明这次招聘的委托关系吗？'
AUTH_REPLY = '我目前无法出示可核实的企业招聘授权。'
INTEREST = '我对你介绍的岗位感兴趣。'
INVITE = '如果愿意，可以做虚构预登记。项目经历和所在城市都可自行选择，不用给真实资料。'
MIXED = '项目经历可以给，所在城市先不提供'
STOP = '我停止整个预登记。'
ATTEMPT = '我提交的项目经历：虚构项目 A'
PURPOSE = '登记资料用来做什么？'

def registration_action(kind, quote, **fields):
    return dict(kind=kind, focus='none', source='own', quote=quote, **fields)

TURNS = {
    INTEREST: ([registration_action('interest', INTEREST, opportunity='chen')], INVITE, [], ()),
    MIXED: ([registration_action('respond_registration', '项目经历可以给', field='project_experience', status='agreed'),
             registration_action('respond_registration', '所在城市先不提供', field='city', status='deferred')], '项目经历只是愿意提供，城市暂缓。两项都还没有提交。', [], ()),
    STOP: ([registration_action('decline', STOP)], '好的，预登记已停止，可以继续聊岗位。', [], ()),
    ATTEMPT: ([registration_action('respond_registration', ATTEMPT, field='project_experience', status='submitted')], '预登记仍已停止，本次没有收下项目资料。', [], ()),
    PURPOSE: ([('ask_data', 'K02')], '原本说是用来汇总意向和安排面试。', [], ()),
    HELLO: ([], '你好，有什么想了解的？', [], ('other','other')),
    QUESTION: ([('verify_friend','K05')], REPLY, [], ('self_denies_job_check','origin')),
    MEMORY_QUESTION: ([('verify_friend','K05')], '我记不清当时问过没有。', [], ('uncertain',)),
    SOURCE_QUESTION: ([('verify_friend','K05')], '我只在群里看过转发。', [], ('origin',)),
    JUDGMENT: ([('identify_gap','K01'),('weigh_sources','K01')], '明白，你想先找依据。', [], ('other','other')),
    AUTH_QUESTION: ([('ask_employer','K01')], AUTH_REPLY, [{'focus':'K01','quote':AUTH_REPLY}], ()),
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
            pairs, reply, disclosures, kinds = TURNS[msg]
            if system in (INTERPRET, K05_INTERPRET, CHEN_INTERPRET):
                result = {'actions':[p if isinstance(p, dict) else {'kind':p[0],'focus':p[1],'quote':msg,'source':'own'} for p in pairs]}
            elif system in (GENERATE, CHEN_GENERATE):
                result = {'body':reply}
            elif system in (AUDIT, K05_AUDIT, CHEN_AUDIT):
                result = {'safe':True,'supported':list(range(len(data['candidates']))),'disclosures':disclosures,'registration_quote':None}
                if system == CHEN_AUDIT:
                    result.update(received_now=[], registration_quote=reply if msg == INTEREST else None)
                if system == K05_AUDIT:
                    result['k05'] = [{'part_id':i, 'kind':kind} for i, kind in enumerate(kinds)]
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


@pytest.mark.parametrize(('question','expected_parts','expect_k05'), [
    (QUESTION, ['没有，','群里看到的。'], True),
    (MEMORY_QUESTION, ['我记不清当时问过没有。'], False),
    (SOURCE_QUESTION, ['我只在群里看过转发。'], False),
], ids=['denial','uncertain','forward-only'])
def test_two_turns_through_compatible_http_contract(wired_session, question, expected_parts, expect_k05):
    client, path, headers, calls = wired_session
    for msg in [question,JUDGMENT]:
        res = client.post(path+'/turns',headers=headers,json={'role':'wang','text':msg,'request_id':str(uuid4())})
        assert 'event: done' in res.text and res.text.count('event: progress') == 3
    report = client.post(path+'/finish',headers=headers,json={'kind':'decision','choice':'verify','reason':JUDGMENT,'cited':[1,2]}).json()
    assert [prompt for prompt,_ in calls] == [K05_INTERPRET,GENERATE,K05_AUDIT]*2
    reply = ''.join(expected_parts)
    audit = calls[2][1]
    assert calls[1][1]['permitted_facts'] == audit['permitted_facts'] == {'K05':FACTS['wang']['K05']}
    assert audit['current_user'] == question and audit['reply'] == reply
    assert audit['reply_parts'] == [{'part_id':i, 'text':part} for i, part in enumerate(expected_parts)]
    for _, payload in calls[3:]:
        assert payload['private_history'] == [{'speaker':'user','text':question}, {'speaker':'assistant','text':reply}]
    if expect_k05:
        ref, = report['disclosures']
        assert (ref['focus'],ref['role'],ref['speaker'],ref['message_id'],ref['quote']) == ('K05','wang','assistant',2,reply)
    else:
        assert report['disclosures'] == []
    risk, = report['dimensions'][0]['evidence']
    assert (risk['speaker'],risk['message_id'],risk['quote']) == ('user',3,JUDGMENT)


def test_stopped_registration_blocks_a_supported_submission_and_keeps_k05_private(wired_session):
    client, path, headers, calls = wired_session
    def send(role, text, rid=None):
        result = client.post(path+'/turns', headers=headers, json={'role':role, 'text':text, 'request_id':rid or str(uuid4())})
        assert 'event: done' in result.text, result.text
        return result
    for text in (INTEREST, MIXED, STOP):
        send('chen', text)
    stopped = client.get(path, headers=headers).json()['registration']
    assert stopped['declined_all'] and [i['status'] for i in stopped['items']] == ['agreed','deferred']
    assert stopped['submitted'] == [] and len(stopped['history']) == 2
    rid = str(uuid4())
    send('chen', ATTEMPT, rid)
    generation, audit = (data for _,data in calls[-2:])
    assert audit['candidates'][0]['status'] == 'submitted'  # The independent stub even supports it.
    assert audit['registration'] == generation['registration']
    assert generation['registration']['stopped_after'] and generation['registration']['this_turn'] == []
    assert not generation['allow_invitation']
    count = len(calls)
    assert '"cached":true' in send('chen', ATTEMPT, rid).text and len(calls) == count
    send('chen', PURPOSE)
    assert not calls[-2][1]['allow_invitation'] and 'K02' in calls[-2][1]['permitted_facts']
    for role, text in [('lin',HELLO), ('wang',QUESTION)]:
        send(role, text)
        for _, data in calls[-3:]:
            assert 'registration' not in data and data['private_history'] == [] and ATTEMPT not in str(data)
    with TestClient(create_app()) as fresh:
        snap = fresh.get(path, headers=headers).json()
        assert snap['registration'] == stopped
        by_id = {m['id']:m for m in snap['messages']}
        for entry in stopped['history']:
            assert entry['quote'] in by_id[entry['message_id']]['body'] and by_id[entry['message_id']]['speaker'] == 'user'
            assert entry['reply_quote'] == by_id[entry['reply_id']]['body']
        report = fresh.post(path+'/finish', headers=headers, json={'kind':'decision','choice':'necessary_only'}).json()
        assert report['ending']['label'] == '仅提交必要资料'
        assert report['registration']['history'] == stopped['history'] and report['registration']['submitted'] == []
        assert [ref['quote'] for ref in report['registration']['references']] == [INVITE, STOP]
        assert [(d['focus'],d['speaker'],d['quote']) for d in report['disclosures']] == [('K05','assistant',REPLY)]
        assert not next(d for d in report['dimensions'] if d['key'] == 'risk')['evidence']


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
        expected_analysis = {'contact':name, 'private_history':[], 'current_user':HELLO}
        if role == 'wang':
            expected_analysis['source_action_guide'] = K05_ACTIONS
        if role == 'chen':
            state = client.get(path, headers=headers).json()['registration']
            expected_analysis['registration'] = {k: state[k] for k in ('items', 'submitted', 'declined_all')} | {'invited':False}
            assert generation['registration']['this_turn'] == []
        else:
            assert all('registration' not in payload for payload in (analysis, generation, audit))
        prompts = {'wang':[K05_INTERPRET,GENERATE,K05_AUDIT], 'chen':[CHEN_INTERPRET,CHEN_GENERATE,CHEN_AUDIT], 'lin':[INTERPRET,GENERATE,AUDIT]}[role]
        assert [prompt for prompt,_ in calls[-3:]] == prompts
        assert analysis == expected_analysis
        assert ('reply_parts' in audit) == (role == 'wang')
        assert generation['character']['name'] == name and 'Python 后端' in generation['scene']
        assert generation['private_history'] == [] and generation['permitted_facts'] == {}
        assert generation['allow_invitation'] is False
        assert all(audit[key] == value for key,value in generation.items())
        visible = json.dumps(generation, ensure_ascii=False)
        assert all(term in visible for term in expected)
        assert not any(term in visible for term in (*excluded, '栖禾', '内容运营', '隐藏设定'))


def test_employer_question_unlocks_only_the_consultants_authorization_clue(wired_session):
    client, path, headers, calls = wired_session
    for role, msg in [('chen',AUTH_QUESTION), ('lin',HELLO), ('wang',HELLO)]:
        res = client.post(path+'/turns',headers=headers,json={'role':role,'text':msg,'request_id':str(uuid4())})
        assert 'event: done' in res.text
    for _,payload in calls[1:3]:
        assert set(payload['permitted_facts']) == {'K01'}
        assert '委托关系' in payload['permitted_facts']['K01'] and not payload['allow_invitation']
    for prompt,payload in calls[3:]:
        assert payload['private_history'] == []
        assert AUTH_REPLY not in json.dumps(payload, ensure_ascii=False)
        if prompt in (GENERATE, AUDIT, K05_AUDIT):
            assert payload['permitted_facts'] == {}
