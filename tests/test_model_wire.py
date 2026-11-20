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
from backend.model import AUDIT, GENERATE, INTERPRET, K05_ACTIONS, K05_AUDIT, K05_INTERPRET, CompatibleModel
from backend.policy import Action, FACTS, Reply, k05_parts, validate_reply

QUESTION = '这机会你亲自问过招聘方吗？'
JUDGMENT = '群里转发不能证明招聘方获得了授权。'
REPLY = '没有，群里看到的。'
MEMORY_QUESTION = '你还记得当时有没有问过招聘方吗？'
SOURCE_QUESTION = '你从哪看到的？'
HELLO = '你好'
AUTH_QUESTION = '你能说明这次招聘的委托关系吗？'
AUTH_REPLY = '我目前无法出示可核实的企业招聘授权。'
INTEREST = '我对你介绍的 Python 实习感兴趣。'
INVITE = '你可以做一次虚构的候选人预登记，项目经历和所在城市都可自行选择，不用给真实资料。'
MIXED = '项目经历可以给，所在城市先不提供'
ACK = '明白，你愿意给项目经历，城市先不提供。现在两项资料我都还没有收到。'
PURPOSE = '登记资料用来做什么？'
PURPOSE_REPLY = '说是为了汇总意向、安排面试，但我说不清为什么初筛就需要简历以外的资料。'
COMBINED = MIXED + '\n我还想问：' + PURPOSE
CITY_AGREED, CITY_DEFERRED = '所在城市可以给', '所在城市先不提供'
CORRECTION = CITY_AGREED + '。算了，' + CITY_DEFERRED
PROJECT_SENT, PROJECT_REFUSED = '我提交的项目经历：虚构项目 A', '我拒绝继续提供项目经历'
SENT_THEN_REFUSED = PROJECT_SENT + '。' + PROJECT_REFUSED
REOPEN = '我改主意了，现在想登记'


def candidate(kind, focus, quote, **attrs):
    return dict(kind=kind, focus=focus, quote=quote, source='own', **attrs)


TURNS = {
    HELLO: ([], '你好，有什么想了解的？', []),
    QUESTION: ([candidate('verify_friend','K05',QUESTION)], REPLY, []),
    MEMORY_QUESTION: ([candidate('verify_friend','K05',MEMORY_QUESTION)], '我记不清当时问过没有。', []),
    SOURCE_QUESTION: ([candidate('verify_friend','K05',SOURCE_QUESTION)], '我只在群里看过转发。', []),
    JUDGMENT: ([candidate(k,'K01',JUDGMENT) for k in ('identify_gap','weigh_sources')], '明白，你想先找依据。', []),
    AUTH_QUESTION: ([candidate('ask_employer','K01',AUTH_QUESTION)], AUTH_REPLY, [{'focus':'K01','quote':AUTH_REPLY}]),
    INTEREST: ([candidate('interest','none',INTEREST,opportunity='chen')], INVITE, []),
    MIXED: ([candidate('respond_registration','none','项目经历可以给',field='project_experience',status='agreed'),
             candidate('respond_registration','none','所在城市先不提供',field='city',status='deferred')], ACK, []),
    PURPOSE: ([candidate('ask_data','K02',PURPOSE)], PURPOSE_REPLY, [{'focus':'K02','quote':PURPOSE_REPLY}]),
    CORRECTION: ([candidate('respond_registration','none',CITY_DEFERRED,field='city',status='deferred'),
                  candidate('respond_registration','none',CITY_AGREED,field='city',status='agreed')], '好的，城市资料暂缓。', []),
    SENT_THEN_REFUSED: ([candidate('respond_registration','none',PROJECT_REFUSED,field='project_experience',status='refused'),
                         candidate('respond_registration','none',PROJECT_SENT,field='project_experience',status='submitted')],
                        '已收到虚构项目 A，不需要再提供项目经历。', []),
    '我不参与预登记。': ([candidate('decline','none','我不参与预登记。')], '明白，不再邀请你登记。', []),
    REOPEN: ([candidate('resume_registration','none',REOPEN)], INVITE, []),
}
TURNS[COMBINED] = (TURNS[MIXED][0] + TURNS[PURPOSE][0], ACK + PURPOSE_REPLY, TURNS[PURPOSE][2])
K05_KINDS = {
    HELLO: ('other','other'), QUESTION: ('self_denies_job_check','origin'),
    MEMORY_QUESTION: ('uncertain',), SOURCE_QUESTION: ('origin',), JUDGMENT: ('other','other'),
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
            candidates, reply, disclosures = TURNS[msg]
            if system in (INTERPRET, K05_INTERPRET):
                result = {'actions':candidates}
            elif system == GENERATE:
                result = {'body':reply}
            elif system in (AUDIT, K05_AUDIT):
                result = {'safe':True,'supported':list(range(len(data['candidates']))),'disclosures':disclosures,'registration_quote':INVITE if msg in (INTEREST, REOPEN) else None}
                if system == K05_AUDIT:
                    result['k05'] = [{'part_id':i, 'kind':kind} for i, kind in enumerate(K05_KINDS[msg])]
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
    _, _, disclosed, _ = validate_reply(Reply(body=reply), audit, [action], FACTS['wang'], set(), None, role='wang')
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


@pytest.mark.parametrize('cite_disclosure', [False, True])
def test_decision_keeps_citations_separate_from_corroborating_evidence(wired_session, cite_disclosure):
    client, path, headers, _ = wired_session
    for msg in [HELLO, QUESTION]:
        res = client.post(path+'/turns', headers=headers, json={'role':'wang','text':msg,'request_id':str(uuid4())})
        assert 'event: done' in res.text
    messages = client.get(path, headers=headers).json()['messages']
    cited = [messages[0]] + ([messages[-1]] if cite_disclosure else [])
    r = client.post(path+'/finish', headers=headers, json={'kind':'decision','choice':'necessary_only',
                    'reason':'','cited':[m['id'] for m in cited]}).json()
    decision = next(d for d in r['dimensions'] if d['key'] == 'decision')
    assert r['ending']['cited'] == [m['id'] for m in cited]
    assert [(e['message_id'],e['quote']) for e in decision['evidence']] == [(m['id'],m['body']) for m in cited]
    assert decision['status'] == ('pending' if cite_disclosure else 'insufficient')
    assert decision['score'] is None and r['total'] is None
    assert client.get(path, headers=headers).json()['review'] == r


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
            registration = dict(client.get(path, headers=headers).json()['registration'], invited=False)
            expected_analysis['registration'] = registration
            assert generation['registration'] == dict(registration, this_turn=[])
        prompts = [K05_INTERPRET,GENERATE,K05_AUDIT] if role == 'wang' else [INTERPRET,GENERATE,AUDIT]
        assert [prompt for prompt,_ in calls[-3:]] == prompts
        assert analysis == expected_analysis
        assert all(('registration' in payload) == (role == 'chen') for payload in (analysis, generation, audit))
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
        assert payload['private_history'] == [] and 'registration' not in payload
        assert AUTH_REPLY not in json.dumps(payload, ensure_ascii=False)
        if prompt in (GENERATE, AUDIT, K05_AUDIT):
            assert payload['permitted_facts'] == {}


def test_partial_registration_survives_reload_and_drives_attributed_review(wired_session):
    client, path, headers, calls = wired_session

    def post(http, role, text, rid=None):
        res = http.post(path+'/turns', headers=headers, json={'role':role,'text':text,'request_id':rid or str(uuid4())})
        assert res.status_code == 200 and 'event: done' in res.text, res.text
        return res

    initial = client.get(path, headers=headers).json()
    openings = {o['role']: o for o in initial['openings']}
    assert set(openings) == {'lin', 'chen'} and all('Python' in o['title'] for o in openings.values())
    assert '招聘平台' in openings['lin']['source'] and '招聘社群' in openings['chen']['source']
    for role, text in [('lin',HELLO), ('wang',QUESTION), ('chen',AUTH_QUESTION)]:
        post(client, role, text)
        assert not calls[-2][1]['allow_invitation']
    assert not client.get(path, headers=headers).json()['registered']
    post(client, 'chen', INTEREST)
    assert calls[-2][1]['allow_invitation'] and client.get(path, headers=headers).json()['registered']

    rid = str(uuid4())
    post(client, 'chen', MIXED, rid)
    assert not calls[-2][1]['allow_invitation']
    length = len(calls)
    assert '"cached":true' in post(client, 'chen', MIXED, rid).text and len(calls) == length
    post(client, 'wang', HELLO)
    assert all('registration' not in payload and MIXED not in str(payload) for _,payload in calls[-3:])

    # A fresh application and HTTP client have no in-memory training state.
    with TestClient(create_app()) as resumed:
        snap = resumed.get(path, headers=headers).json()
        state = snap['registration']
        user, reply = (next(m for m in snap['messages'] if m['body'] == b) for b in (MIXED,ACK))
        assert {i['key']:(i['status'],i['quote'],i['message_id']) for i in state['items']} == {
            'project_experience':('agreed','项目经历可以给',user['id']), 'city':('deferred','所在城市先不提供',user['id'])}
        assert state['submitted'] == []
        post(resumed, 'chen', PURPOSE)
        ctx = calls[-2][1]
        assert ctx['registration']['items'] == state['items'] and not ctx['registration']['declined_all']
        assert not ctx['allow_invitation'] and 'K02' in ctx['permitted_facts']
        reason = '先弄清每项资料为什么必要，再决定是否提交。'
        r = resumed.post(path+'/finish', headers=headers, json={'kind':'decision','choice':'necessary_only',
                         'reason':reason,'cited':[user['id'],reply['id']]}).json()
        assert r['ending']['label'] == '仅提交必要资料' and r['ending']['reason'] == reason
        assert r['registration']['submitted'] == [] and r['registration']['items'] == state['items']
        log = r['registration']['history']
        assert [(e['field'],e['status'],e['quote']) for e in log] == [
            ('project_experience','agreed','项目经历可以给'), ('city','deferred','所在城市先不提供')]
        assert all((e['message_id'],e['reply_id'],e['reply_quote']) == (user['id'],reply['id'],ACK) for e in log)
        decision = next(d for d in r['dimensions'] if d['key'] == 'decision')
        assert [(e['speaker'],e['quote']) for e in decision['evidence']] == [('user',MIXED),('assistant',ACK)]
        assert any(e['quote'] == PURPOSE_REPLY and e['speaker'] == 'assistant' for e in r['disclosures'])
        wang_reply = next(m for m in snap['messages'] if m['role'] == 'wang' and m['body'] == REPLY)
        k05, = [e for e in r['disclosures'] if e['focus'] == 'K05']
        assert (k05['speaker'], k05['message_id'], k05['quote']) == ('assistant', wang_reply['id'], REPLY)
        assert next(d for d in r['dimensions'] if d['key'] == 'risk')['evidence'] == []
        checks = {f['focus']:f for f in r['follow_ups']}
        assert '仍非独立证明' in checks['K02']['basis'] and '尚无核实' in checks['K03']['basis']
        assert resumed.get(path, headers=headers).json()['review'] == r
