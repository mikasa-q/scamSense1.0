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
from backend.model import LIN_AUDIT, CHEN_AUDIT, CHEN_GENERATE, CHEN_INTERPRET, GENERATE, INTERPRET, K05_ACTIONS, K05_AUDIT, K05_INTERPRET, WANG_GENERATE, CompatibleModel
from backend.policy import Action, FACTS, Reply, k05_parts, permission, validate_reply

QUESTION = '这机会你亲自问过招聘方吗？'
JUDGMENT = '群里转发不能证明招聘方获得了授权。'
REPLY = '没有，群里看到的。'
MEMORY_QUESTION = '你还记得当时有没有问过招聘方吗？'
SOURCE_QUESTION = '你从哪看到的？'
WANG_STARTER = '你是从哪里看到这条招聘消息的？'
CHEN_STARTER = '你和招聘企业是什么关系？'
LIN_STARTER = '这个岗位的正式招聘流程在哪里可以核对？'
SOURCE_REPLY = '我只在群里看过转发。'
HELLO = '你好。'
AUTH_QUESTION = '你能说明这次招聘的委托关系吗？'
AUTH_REPLY = '我目前无法出示可核实的企业招聘授权。'
INTEREST = '我对你介绍的岗位感兴趣。'
INVITE = '如果愿意，可以做虚构预登记。项目经历和所在城市都可自行选择，不用给真实资料。'
MIXED = '项目经历可以给，所在城市先不提供'
STOP = '我停止整个预登记。'
ATTEMPT = '我提交的项目经历：虚构项目 A'
PURPOSE = '登记资料用来做什么？'
RESUME = '我想重新开始整个预登记。'
PROJECT_TEXT = '项目经历：虚构项目 A，多谢！'
CITY_TEXT = '我现在提交所在城市：虚构城市 B。'
LIN_ASK = '我可以从哪里单独核对你负责的这次面试？'
LIN_ROUTE = '你可以从公司公开招聘页面找到岗位，联系页面上的招聘团队核对我安排的面试。这只能核对我的流程，不能证实群里的转发。'
CHEN_ASK = '这条转发有没有官方公告或招聘编号可以自己核对？'
CHEN_GAP = '我目前拿不出能独立核对这条转发的招聘编号或官方公告。'
OWN_JUDGMENT = '没有可对照的公告，我就不能仅凭这条转发认定招聘是真的。'
VAGUE_ASK = '只说平时用什么方式联系，能让我独立核对吗？'
VAGUE_REPLY = '我们一般用邮箱联系。'

def registration_action(kind, quote, **fields):
    return dict(kind=kind, focus='none', source='own', quote=quote, **fields)

def friend_inquiry(quote, inquiry):
    return dict(kind='verify_friend', focus='K05', source='own', quote=quote, inquiry=inquiry)

TURNS = {
    WANG_STARTER: ([friend_inquiry(WANG_STARTER, 'forward_source')], SOURCE_REPLY, [], ('origin',)),
    LIN_STARTER: ([('verify_official','K04')], LIN_ROUTE, [], ()),
    CHEN_STARTER: ([('ask_employer','K01')], AUTH_REPLY, [{'focus':'K01','quote':AUTH_REPLY}], ()),
    LIN_ASK: ([('verify_official','K04')], LIN_ROUTE, [{'focus':'K04', 'quote':'公开招聘页面'}], ()),
    CHEN_ASK: ([('verify_official','K04')], CHEN_GAP, [], ()),
    OWN_JUDGMENT: ([('identify_gap','K04'), ('weigh_sources','K04')], '理解，你希望依据独立信息来判断。', [], ()),
    VAGUE_ASK: ([('verify_official','K04')], VAGUE_REPLY, [], ()),
    PROJECT_TEXT: ([registration_action('respond_registration', PROJECT_TEXT, field='project_experience', status='submitted')], '项目资料没有通过聊天提交。可以点「提交虚构项目 A」。', [], ()),
    CITY_TEXT: ([registration_action('respond_registration', CITY_TEXT, field='city', status='submitted')], '想确认这项，可以点「提交虚构城市 B」。', [], ()),
    RESUME: ([registration_action('resume_registration', RESUME)], '预登记已经恢复，可以继续选择你要提交的虚构资料。', [], ()),
    INTEREST: ([registration_action('interest', INTEREST, opportunity='chen')], INVITE, [], ()),
    MIXED: ([registration_action('respond_registration', '项目经历可以给', field='project_experience', status='agreed'),
             registration_action('respond_registration', '所在城市先不提供', field='city', status='deferred')], '项目经历只是愿意提供，城市暂缓。两项都还没有提交。', [], ()),
    STOP: ([registration_action('decline', STOP)], '好的，预登记已停止，可以继续聊岗位。', [], ()),
    ATTEMPT: ([registration_action('respond_registration', ATTEMPT, field='project_experience', status='submitted')], '预登记仍已停止，本次没有收下项目资料。', [], ()),
    PURPOSE: ([('ask_data', 'K02')], '原本说是用来汇总意向和安排面试。', [], ()),
    HELLO: ([], '你好，有什么想了解的？', [], ('other','other')),
    QUESTION: ([friend_inquiry(QUESTION, 'personal_check')], REPLY, [], ('self_denies_job_check','origin')),
    MEMORY_QUESTION: ([friend_inquiry(MEMORY_QUESTION, 'personal_check')], '我记不清当时问过没有。', [], ('uncertain',)),
    SOURCE_QUESTION: ([friend_inquiry(SOURCE_QUESTION, 'forward_source')], SOURCE_REPLY, [], ('origin',)),
    JUDGMENT: ([('identify_gap','K01'),('weigh_sources','K01')], '明白，你想先找依据。', [], ('other','other')),
    AUTH_QUESTION: ([('ask_employer','K01')], AUTH_REPLY, [{'focus':'K01','quote':AUTH_REPLY}], ()),
}

@contextmanager
def wire_fixture(api_root='/v1'):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            system = request['messages'][0]['content']
            data = json.loads(request['messages'][1]['content'])
            msg = data['current_user']
            if self.path != api_root + '/chat/completions' or msg not in TURNS or self.headers.get('Authorization'):
                self.send_error(400); return
            calls.append((system,data))
            pairs, reply, disclosures, kinds = TURNS[msg]
            if system in (INTERPRET, K05_INTERPRET, CHEN_INTERPRET):
                result = {'actions':[p if isinstance(p, dict) else {'kind':p[0],'focus':p[1],'quote':msg,'source':'own'} for p in pairs]}
            elif system in (GENERATE, WANG_GENERATE, CHEN_GENERATE):
                result = {'body':reply}
            elif system in (LIN_AUDIT, K05_AUDIT, CHEN_AUDIT):
                k04 = {LIN_STARTER:'k04_interview_route', LIN_ASK:'k04_interview_route', CHEN_ASK:'k04_missing_reference'}.get(msg, 'none')
                result = {'safe':True,'k04':k04,'supported':list(range(len(data['candidates']))),'disclosures':disclosures,'registration_quote':None}
                if system == CHEN_AUDIT:
                    stance = {STOP:'stopped', ATTEMPT:'stopped', RESUME:'open', PROJECT_TEXT:'open', CITY_TEXT:'open'}
                    result.update(received_now=[], previously_received=[], reply_availability=stance.get(msg,'unstated'),
                                  registration_quote=reply if msg == INTEREST else None)
                if system == K05_AUDIT:
                    result['k05'] = [{'part_id':i, 'kind':kind} for i, kind in enumerate(kinds)]
            else:
                self.send_error(400); return
            body = json.dumps({'choices':[{'message':{'role':'assistant','content':json.dumps(result,ensure_ascii=False)}}]},ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        th = threading.Thread(target=server.serve_forever,daemon=True); th.start()
        try: yield f'http://127.0.0.1:{server.server_port}{api_root}', calls
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
@pytest.mark.parametrize(('question','inquiry','previously_disclosed','reply','evidence'), [
    (QUESTION, 'personal_check', False, '没有，群里看到的。', ('没有',)),
    (QUESTION, 'personal_check', False, '没有，我只看了群转发，没跟招聘方打过交道。', ('没有', '没跟招聘方打过交道')),
    ('我在整理校园招聘的信息渠道，你是在校园群、公众号还是学校网站看到这条消息的？', 'forward_source', True,
     '我在校园群看到的，当时觉得挺有意思的，但没去查真伪。', ('没去查真伪',)),
    ('这条消息是你从学校官网看到的吗？', 'forward_source', False, '没有，群里看到的。', ()),
    (SOURCE_QUESTION, 'forward_source', False, '校园群里有人转发过。', ()),
    (SOURCE_QUESTION, 'forward_source', False, '我是在群里看到的，没问清楚源头。', ()),
    (QUESTION, 'personal_check', False, '发给我的同学没亲自核实。', ()),
    (QUESTION, 'personal_check', False, '我记不清当时问过没有。', ()),
], ids=['elliptical', 'natural', 'mixed', 'elliptical-origin', 'source', 'forward-origin', 'other-person', 'uncertain'])
def test_live_k05_judgment(question, inquiry, previously_disclosed, reply, evidence):
    action = Action(**friend_inquiry(question, inquiry))
    previous = {'K05'} if previously_disclosed else set()
    history = [{'speaker':'user','text':QUESTION}, {'speaker':'assistant','text':REPLY}] if previous else []
    facts, _ = permission('wang', [action], previous, None)
    audit = asyncio.run(CompatibleModel().audit('wang', history, question, facts, False, [action], reply))
    assert audit.supported == [0] and audit.k05 is not None
    _, _, disclosed, _ = validate_reply(Reply(body=reply), audit, [action], facts, previous, False, role='wang')
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
    assert [prompt for prompt,_ in calls] == [K05_INTERPRET,WANG_GENERATE,K05_AUDIT]*2
    reply = ''.join(expected_parts)
    audit = calls[2][1]
    expected_facts = {} if question == SOURCE_QUESTION else {'K05':FACTS['wang']['K05']}
    assert calls[1][1]['permitted_facts'] == audit['permitted_facts'] == expected_facts
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
    assert generation['registration']['availability'] == 'stopped' and generation['registration']['this_turn'] == []
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


def test_only_confirmations_write_through_stop_and_restart(wired_session):
    client, path, headers, calls = wired_session
    def send(text):
        res = client.post(path+'/turns', headers=headers, json={'role':'chen', 'text':text, 'request_id':str(uuid4())})
        assert 'event: done' in res.text
        return client.get(path, headers=headers).json()
    def confirm(option):
        count = len(calls)
        res = client.post(path+'/contacts/chen/registration/confirm', headers=headers, json={'option_id':option})
        assert len(calls) == count
        return res
    send(INTEREST)
    assert send(PROJECT_TEXT)['registration']['history'] == []
    assert calls[-1][1]['candidates'][0]['status'] == 'submitted' and not calls[-1][1]['registration']['this_turn']
    assert confirm('project_a').json()['registration']['submitted'] == ['project_experience']
    snap = send(STOP)
    assert confirm('city_b').status_code == 409 and client.get(path, headers=headers).json() == snap
    snap = send(RESUME)
    assert snap['registered'] and not snap['registration']['declined_all'] and len(snap['registration']['history']) == 1
    for _, payload in calls[-2:]:
        assert payload['registration']['availability'] == 'open' and not payload['allow_invitation']
        assert 'declined_all' not in payload['registration'] and payload['registration']['submitted'] == ['project_experience']
    assert send(CITY_TEXT)['registration'] == snap['registration']
    confirmed = confirm('city_b').json()
    assert confirmed['registration']['submitted'] == ['project_experience','city']
    for role in ['lin','wang']:
        result = client.post(path+'/turns', headers=headers, json={'role':role,'text':HELLO,'request_id':str(uuid4())})
        assert 'event: done' in result.text
        for _, data in calls[-3:]:
            assert 'registration' not in data and data['private_history'] == [] and '虚构项目 A' not in str(data)
    with TestClient(create_app()) as fresh:
        assert fresh.get(path, headers=headers).json()['registration'] == confirmed['registration']
        report = fresh.post(path+'/finish', headers=headers, json={'kind':'decision','choice':'necessary_only'}).json()
        assert report['registration']['history'] == confirmed['registration']['history']
        assert [ref['quote'] for ref in report['registration']['references']] == [INVITE, STOP, RESUME]


def test_second_training_never_inherits_history_facts_or_registration(wired_session):
    client, first, first_headers, calls = wired_session
    other = client.post('/api/sessions').json()
    second, second_headers = '/api/sessions/' + other['id'], {'Authorization':'Bearer ' + other['token']}
    shared_id = str(uuid4())
    def send(path, headers, role, text, rid=None):
        result = client.post(path+'/turns', headers=headers, json={'role':role, 'text':text, 'request_id':rid or str(uuid4())})
        assert 'event: done' in result.text
        return [data for _, data in calls[-3:]]
    send(first, first_headers, 'chen', INTEREST, shared_id)
    send(first, first_headers, 'chen', CHEN_ASK)
    assert client.post(first+'/contacts/chen/registration/confirm', headers=first_headers, json={'option_id':'project_a'}).is_success
    for role, msg in [('chen', HELLO), ('wang', QUESTION), ('lin', LIN_ASK)]:
        analysis, gen, audit = send(second, second_headers, role, msg, shared_id if role == 'chen' else None)
        assert analysis['private_history'] == gen['private_history'] == audit['private_history'] == []
        if role == 'chen':
            assert not gen['permitted_facts'] and gen['registration']['availability'] == 'not_invited'
            assert not gen['registration']['submitted'] and not analysis['registration']['invited']
        else:
            assert all('registration' not in payload for payload in (analysis, gen, audit))
    for path, headers, role, expected in [(first, first_headers, 'chen', [INTEREST, INVITE, CHEN_ASK, CHEN_GAP]),
                                          (second, second_headers, 'chen', [HELLO, TURNS[HELLO][1]])]:
        for payload in send(path, headers, role, HELLO):
            assert [m['text'] for m in payload['private_history']] == expected
    assert client.get(second, headers=first_headers).status_code == 404
    assert [m['role'] for m in client.get(first, headers=first_headers).json()['messages']] == ['chen']*6
    assert not client.get(second, headers=second_headers).json()['registration']['submitted']


def test_closed_app_reopens_the_same_complete_archive(tmp_path, monkeypatch):
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', f'sqlite:///{(tmp_path / "restart.db").as_posix()}')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, 'head')
    with wire_fixture('/provider-root') as (base, calls):
        monkeypatch.setenv('OPENAI_BASE_URL', base)
        with TestClient(create_app()) as client:
            session = client.post('/api/sessions').json()
            path, hdr = '/api/sessions/'+session['id'], {'Authorization':'Bearer '+session['token']}
            for role, msg in [('wang', QUESTION), ('chen', INTEREST), ('chen', MIXED), ('lin', LIN_ASK)]:
                turn = {'role':role, 'text':msg, 'request_id':str(uuid4())}
                assert 'event: done' in client.post(path+'/turns', headers=hdr, json=turn).text
            for _ in range(2):
                r = client.post(path+'/contacts/chen/registration/confirm', headers=hdr, json={'option_id':'project_a'})
                assert r.is_success
            active = client.get(path, headers=hdr).json()
            assert len(active['messages']) == 8 and active['registration']['submitted'] == ['project_experience']
            assert len([e for e in active['registration']['history'] if e['source']=='explicit']) == 1
        command.upgrade(config, 'head')
        with TestClient(create_app()) as restarted:
            assert restarted.get(path, headers=hdr).json() == active
            assert '"cached":true' in restarted.post(path+'/turns', headers=hdr, json=turn).text
            ending = {'kind':'decision', 'choice':'necessary_only', 'reason':JUDGMENT, 'cited':[active['messages'][1]['id']]}
            report = restarted.post(path+'/finish', headers=hdr, json=ending).json()
            assert [e['focus'] for e in report['disclosures']] == ['K05', 'K04']
            archived = restarted.get(path, headers=hdr).json()
            assert archived['review'] == report and archived['closed']
    # Reading the archive and replaying completed operations needs no provider.
    monkeypatch.delenv('OPENAI_BASE_URL')
    with TestClient(create_app()) as offline:
        assert offline.get(path, headers=hdr).json() == archived
        assert offline.post(path+'/finish', headers=hdr, json=ending).json() == report
        assert '"cached":true' in offline.post(path+'/turns', headers=hdr, json=turn).text
    assert len(calls) == 12


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
        prompts = {'wang':[K05_INTERPRET,WANG_GENERATE,K05_AUDIT], 'chen':[CHEN_INTERPRET,CHEN_GENERATE,CHEN_AUDIT], 'lin':[INTERPRET,GENERATE,LIN_AUDIT]}[role]
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


@pytest.mark.parametrize(('retold', 'finding', 'supported', 'rejection'), [
    (False, 'k04_interview_route', [1], None),
    (False, 'none', [1], None),
    (True, 'k04_interview_route', [], 'k04_unverified'),
    (False, 'unsupported_claim', [1], 'k04_unsupported'),
], ids=['own-question-and-route','own-question-without-route','retold-question','unsupported-endorsement'])
def test_lin_audit_keeps_question_and_reply_independent(monkeypatch, retold, finding, supported, rejection):
    from backend.diagnostics import RuleRejected
    from backend.policy import Audit
    question = '这个岗位的正式招聘流程在哪里可以核对？'
    text = f'同学问过「{question}」，我只是转述。' if retold else question
    reply = {'k04_interview_route':LIN_ROUTE, 'none':VAGUE_REPLY, 'unsupported_claim':'这条群转发已由公司证实。'}[finding]
    actions = [Action(kind=kind, focus='K04', source='own', quote=question) for kind in ('identify_gap','verify_official')]
    adapter = CompatibleModel()
    async def reviewer(system, payload, schema, *, temperature):
        assert system == LIN_AUDIT and schema is Audit and temperature == 0
        assert payload['current_user'] == text and payload['reply'] == reply
        assert payload['candidates'] == [dict(index=i, **a.model_dump(exclude_none=True)) for i,a in enumerate(actions)]
        return Audit(safe=True, k04=finding, supported=supported, disclosures=[], registration_quote=None)
    monkeypatch.setattr(adapter, '_json', reviewer)
    audit = asyncio.run(adapter.audit('lin', [], text, FACTS['lin'], False, actions, reply))
    def validate(): return validate_reply(Reply(body=reply), audit, actions, FACTS['lin'], set(), False, role='lin')
    if rejection:
        with pytest.raises(RuleRejected) as refused: validate()
        assert refused.value.rule.name == rejection
    else:
        _, valid, disclosed, _ = validate()
        assert valid == [actions[1]] and disclosed == ({'K04':reply} if finding == 'k04_interview_route' else {})


@pytest.mark.parametrize('add_judgment', [False, True], ids=['questions-only', 'later-own-judgment'])
def test_k04_separates_asks_role_outcomes_and_own_reasoning(wired_session, add_judgment):
    client, path, headers, calls = wired_session
    turns = [('lin', LIN_ASK), ('chen', CHEN_ASK), ('wang', QUESTION)]
    if add_judgment:
        turns.append(('chen', OWN_JUDGMENT))
    for i, (role, text) in enumerate(turns):
        res = client.post(path+'/turns', headers=headers, json={'role':role, 'text':text, 'request_id':str(uuid4())})
        assert 'event: done' in res.text
        analysis, generation, audit = (data for _, data in calls[-3:])
        assert analysis['private_history'] == generation['private_history'] == audit['private_history'] == (
            [] if i < 3 else [{'speaker':'user','text':CHEN_ASK}, {'speaker':'assistant','text':CHEN_GAP}])
        focus = 'K05' if role == 'wang' else 'K04'
        assert generation['permitted_facts'] == audit['permitted_facts'] == {focus:FACTS[role][focus]}
    snap = client.get(path, headers=headers).json()
    assert not snap['registered'] and not snap['registration']['history']
    msgs = snap['messages']
    report = client.post(path+'/finish', headers=headers, json={'kind':'early'}).json()
    def refs(entries):
        return [(e['role'], e['speaker'], e['message_id'], e['quote']) for e in entries]
    dims = {d['key']:d['evidence'] for d in report['dimensions']}
    assert refs(dims['verify']) == [(role, 'user', msgs[2*i]['id'], text) for i, (role, text) in enumerate(turns[:3])]
    assert refs(report['disclosures']) == [('lin','assistant',msgs[1]['id'],LIN_ROUTE),
                                            ('chen','assistant',msgs[3]['id'],CHEN_GAP),
                                            ('wang','assistant',msgs[5]['id'],REPLY)]
    assert [e['focus'] for e in report['disclosures']] == ['K04','K04','K05']
    assert [e['topic'] for e in report['disclosures'][:2]] == ['本人面试的独立核对途径', '转发目前缺少可核对依据']
    expected = [('chen','user',msgs[6]['id'],OWN_JUDGMENT)] if add_judgment else []
    assert refs(dims['risk']) == refs(dims['sources']) == expected
    assert client.get(path, headers=headers).json()['review'] == report


def test_k04_still_available_after_stopping_registration(wired_session):
    client, path, headers, calls = wired_session
    for msg in (INTEREST, STOP, CHEN_ASK):
        res = client.post(path+'/turns', headers=headers, json={'role':'chen', 'text':msg, 'request_id':str(uuid4())})
        assert 'event: done' in res.text
    assert calls[-1][1]['registration']['availability'] == 'stopped'
    report = client.post(path+'/finish', headers=headers, json={'kind':'early'}).json()
    assert report['registration']['declined_all'] and not report['registration']['submitted']
    assert [e['quote'] for e in report['disclosures']] == [CHEN_GAP]


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
        if prompt in (GENERATE, LIN_AUDIT, K05_AUDIT):
            assert payload['permitted_facts'] == {}
