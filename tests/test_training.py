import json
from types import SimpleNamespace
from uuid import uuid4
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from backend import training
from backend.db import ROOT, Receipt, StoryEvent, Trace, Training
from backend.main import create_app
from backend.model import CompatibleModel
from backend.policy import Action, Analysis, Audit, Disclosure, Reply

ASK = '你亲自核实过这个岗位吗？'
ANSWER = '我在校园群里看到转发，没亲自核实。'
JUDGE = '群里转发不能证明招聘方获得了授权。'

def action(kind, focus, quote, source='own', **attrs):
    return Action(kind=kind, focus=focus, quote=quote, source=source, **attrs)

class ScriptedModel:
    configured = True
    def __init__(self):
        self.actions = [action('verify_friend','K05',ASK)]
        self.body = ANSWER
        self.disclosures = [Disclosure(focus='K05',quote='没亲自核实。')]
        self.supported = None
        self.safe = True
        self.break_at = None
        self.reg = None
        self.calls = []
    async def analyze(self, role, history, text, registration):
        self.calls.append(('analysis',role,history,text))
        if self.break_at == 'analysis': raise RuntimeError()
        return Analysis(actions=self.actions)
    async def reply(self, role, history, text, facts, invite, registration):
        self.calls.append(('reply',role,history,dict(facts),invite))
        if self.break_at == 'reply': raise RuntimeError()
        return Reply(body=self.body)
    async def audit(self, role, history, text, facts, invite, actions, body, registration):
        self.calls.append(('audit',role,history,dict(facts),invite))
        if self.break_at == 'audit': raise RuntimeError()
        return Audit(safe=self.safe, supported=list(range(len(actions))) if self.supported is None else self.supported, disclosures=self.disclosures, registration_quote=self.reg)

@pytest.fixture
def lab(tmp_path, monkeypatch):
    url = f'sqlite:///{(tmp_path / "one.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL',url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')),'head')
    model = ScriptedModel()
    app = create_app(url, model)
    with TestClient(app) as client:
        s = client.post('/api/sessions').json()
        path, hdr = '/api/sessions/' + s['id'], {'Authorization':'Bearer '+s['token']}
        def post(text=ASK, role='wang', rid=None):
            return client.post(path+'/turns',headers=hdr,json={'role':role,'text':text,'request_id':rid or str(uuid4())})
        def end(**data):
            return client.post(path+'/finish',headers=hdr,json=data)
        yield SimpleNamespace(client=client,model=model,post=post,end=end,path=path,hdr=hdr,app=app,sid=s['id'],snap=lambda:client.get(path,headers=hdr).json())

def report_dims(report):
    return {d['key']:d for d in report['dimensions']}

def test_full_evidence_chain_is_attributed_and_recoverable(lab):
    assert 'event: done' in lab.post().text
    first = lab.snap()['messages']
    lab.model.actions = [action('identify_gap','K01',JUDGE),action('weigh_sources','K01',JUDGE)]
    lab.model.body, lab.model.disclosures = '明白，你想把这个说法单独核对。', []
    assert 'event: done' in lab.post(JUDGE).text
    snap = lab.snap()
    r = lab.end(kind='decision', choice='verify',reason='群里的消息并非独立证据。',cited=[first[1]['id']]).json()
    dims = report_dims(r)
    assert [d['weight'] for d in r['dimensions']] == [25,30,25,20]
    assert dims['verify']['evidence'][0]['message_id'] == first[0]['id']
    assert dims['risk']['evidence'][0]['message_id'] == snap['messages'][2]['id']
    assert dims['sources']['evidence'][0]['speaker'] == 'user'
    assert r['disclosures'][0]['message_id'] == first[1]['id']
    assert r['disclosures'][0]['focus'] == 'K05' and len(r['disclosures']) == 1
    assert dims['decision']['evidence'][0]['quote'] == ANSWER
    assert r['total'] is None and all(d['score'] is None for d in r['dimensions'])
    assert lab.snap()['review'] == r and lab.snap()['stage'] == 6
    assert lab.post().status_code == 409

@pytest.mark.parametrize('overclaims',[True,False])
def test_source_only_is_not_k05(lab, overclaims):
    lab.model.body = '我在群里看到过。'
    lab.model.disclosures = [Disclosure(focus='K05', quote=lab.model.body)] if overclaims else []
    assert 'event: done' in lab.post().text
    r = lab.end(kind='early').json()
    assert r['disclosures'] == []
    assert report_dims(r)['risk']['status'] == 'insufficient'
    assert report_dims(r)['verify']['evidence']

def test_role_and_session_isolation(lab):
    lab.post()
    lab.model.body, lab.model.actions, lab.model.disclosures = '我只了解自己负责的招聘。', [], []
    lab.post('你好','lin')
    assert lab.model.calls[-2][2:4] == ([],{})
    second = lab.client.post('/api/sessions').json()
    hdr = {'Authorization':'Bearer '+second['token']}
    assert lab.client.get(lab.path,headers=hdr).status_code == 404
    assert lab.client.get(lab.path).status_code == 401
    assert not lab.client.get('/api/sessions/'+second['id'],headers=hdr).json()['messages']
    assert lab.client.post('/api/sessions/'+second['id']+'/finish',headers=hdr,json={'kind':'decision','choice':'leave','cited':[lab.snap()['messages'][0]['id']]}).status_code == 422

@pytest.mark.parametrize('failure',['analysis','reply','audit','unsafe','badquote','unapproved','sensitive','solicitation','unsupported'])
def test_model_failure_rolls_back_and_original_id_retries(lab, failure):
    rid = str(uuid4())
    lab.model.break_at = failure
    if failure == 'unsafe': lab.model.safe = False
    if failure == 'unsupported': lab.model.supported = []
    if failure == 'badquote': lab.model.disclosures = [Disclosure(focus='K05',quote='并未说过这句话')]
    if failure == 'unapproved': lab.model.disclosures = [Disclosure(focus='K04',quote=ANSWER)]
    if failure == 'sensitive': lab.model.body = '请写邮件至 demo@example.org'
    if failure == 'solicitation': lab.model.body = '请提供你的真实手机号。'
    failed = lab.post(rid=rid)
    assert 'event: error' in failed.text and 'event: done' not in failed.text
    assert not lab.snap()['messages'] and not lab.snap()['busy'] and lab.snap()['stage'] == 0
    with lab.app.state.factory() as db:
        assert list(db.scalars(select(StoryEvent.kind))) == ['created']
        assert not list(db.scalars(select(Trace.id)))
    lab.model.break_at, lab.model.safe, lab.model.supported = None,True,None
    lab.model.body, lab.model.disclosures = ANSWER,[Disclosure(focus='K05',quote='没亲自核实。')]
    assert 'event: done' in lab.post(rid=rid).text
    assert len(lab.snap()['messages']) == 2

def test_receipt_replay_after_refresh_and_finish(lab):
    rid = str(uuid4())
    lab.post(rid=rid)
    before = lab.snap(); calls = len(lab.model.calls)
    assert '"cached":true' in lab.post(rid=rid).text
    assert lab.post('不同正文',rid=rid).status_code == 409
    assert lab.post(role='chen',rid=rid).status_code == 409
    archived = lab.end(kind='early').json()
    assert '"cached":true' in lab.post(rid=rid).text
    assert lab.snap()['messages'] == before['messages'] and len(lab.model.calls) == calls
    assert len(archived['disclosures']) == 1 and len(report_dims(archived)['verify']['evidence']) == 1

def test_retelling_or_unmatched_quotes_do_not_generate_user_evidence(lab):
    lab.model.actions = [action('weigh_sources','K05','不能作证','retold'),action('identify_gap','K04','不在原文中'),action('verify_friend','K05','没问过','uncertain')]
    lab.model.body, lab.model.disclosures = '知道了。',[]
    assert 'event: done' in lab.post('对方说不能作证，没问过本人。').text
    r = lab.end(kind='decision',choice='leave').json()
    assert all(d['status'] == 'insufficient' for d in r['dimensions']) and r['total'] is None

def test_early_end_is_not_a_recruitment_decision(lab):
    assert lab.end(kind='early',choice='leave').status_code == 422
    r = lab.end(kind='early').json()
    assert r['ending']['choice'] is None and r['ending']['kind'] == 'early'
    assert lab.end(kind='early').json() == r
    assert lab.end(kind='decision',choice='verify').status_code == 409
    with lab.app.state.factory() as db:
        assert list(db.scalars(select(StoryEvent.kind))) == ['created','completed']

@pytest.mark.parametrize('value',['138 0000 0000','demo@example.org','证件号 00000000000000000X','住在示例路12号'])
def test_privacy_rejects_before_receipt_or_model(lab, value):
    assert lab.post(value).status_code == 422
    assert lab.end(kind='decision',choice='verify',reason=value).status_code == 422
    assert not lab.model.calls and not lab.snap()['messages']
    with lab.app.state.factory() as db: assert not list(db.scalars(select(Receipt.id)))

def test_unconfigured_is_explicit_and_server_does_not_offer_fake_mode(lab):
    lab.model.configured = False
    assert lab.client.get('/api/health').json()['model_configured'] is False
    assert lab.post().status_code == 503 and not lab.model.calls
    assert not lab.snap()['messages']
    assert lab.client.post(lab.path+'/turns',headers=lab.hdr,json={'role':'wang','text':ASK,'request_id':str(uuid4()),'mock':True}).status_code == 422

def test_concurrent_and_stale_attempts_cannot_commit(lab):
    factory, rid = lab.app.state.factory, str(uuid4())
    receipt, expired = training.reserve(factory,lab.sid,rid,'wang',ASK,True)
    assert lab.post(rid=rid).status_code == 409 and lab.end(kind='early').status_code == 409
    assert lab.snap()['busy']
    with factory.begin() as db: db.get(Training,lab.sid).lock_until = 0
    _, fresh = training.reserve(factory,lab.sid,rid,'wang',ASK,True)
    assert fresh != expired
    with pytest.raises(ValueError): training.store_turn(factory,lab.sid,receipt,expired,'wang',ASK,ANSWER,[],{},None,False)
    training.fail_turn(factory,lab.sid,receipt,expired)
    assert lab.snap()['busy'] and not lab.snap()['messages']
    training.fail_turn(factory,lab.sid,receipt,fresh)
    assert 'event: done' in lab.post(rid=rid).text

def test_registration_is_an_actual_proposal_and_refusal_is_respected(lab):
    model = lab.model; interested = '我想了解这个岗位。'
    model.actions,model.disclosures = [action('interest','none',interested,opportunity='chen')],[]
    model.body,model.reg = '可以做虚构意向预登记，不需要实际资料。','可以做虚构意向预登记'
    lab.post(interested,'chen');assert lab.snap()['registered'] and lab.snap()['stage'] == 2
    no = '我不愿意登记。';model.actions = [action('decline','none',no)];model.reg=None;model.body='明白，我尊重你的决定。'
    lab.post(no,'chen');model.actions=[action('interest','none',interested,opportunity='chen')]
    lab.post(interested,'chen');assert model.calls[-2][-1] is False

@pytest.mark.parametrize('role,target,source', [('chen','lin','own'),('lin','chen','own'),('chen','chen','retold'),('wang','chen','own')])
def test_interest_must_be_own_and_directed_to_consultant(lab, role, target, source):
    text = '同学对这份实习感兴趣。' if source == 'retold' else '我对林悦的岗位感兴趣。'
    model = lab.model
    model.actions = [action('interest','none',text,source,opportunity=target)]
    model.disclosures, model.body = [], '可以继续核实岗位信息。'
    assert 'event: done' in lab.post(text, role).text
    assert not model.calls[-2][-1] and not lab.snap()['registered']
    model.body = model.reg = '要参加预登记吗？'
    assert 'event: error' in lab.post(text, role).text and not lab.snap()['registered']


def propose(lab):
    model = lab.model
    interest = '我想应聘你介绍的这个岗位。'
    model.actions = [action('interest','none',interest,opportunity='chen')]
    model.disclosures, model.body = [], '可以自愿做虚构资料的预登记。'
    model.reg = model.body
    assert 'event: done' in lab.post(interest,'chen').text
    model.reg = None
    return model


def test_partial_refusal_actual_submission_and_later_change_of_mind(lab):
    model = propose(lab)
    project, city = '我提交的项目经历：虚构项目 A', '我拒绝提供所在城市'
    model.actions = [action('respond_registration','none',project,field='project_experience',status='submitted'),
                     action('respond_registration','none',city,field='city',status='refused')]
    model.body = '收到了虚构项目 A，城市不必提供。'
    assert 'event: done' in lab.post(project+'，'+city,'chen').text
    r = lab.snap()['registration']
    assert [i['status'] for i in r['items']] == ['submitted','refused'] and r['submitted'] == ['project_experience']
    last = '项目经历之后先不提供。'
    model.actions = [action('respond_registration','none',last,field='project_experience',status='deferred')]
    model.body = '可以，不需要继续给项目资料。'
    assert 'event: done' in lab.post(last,'chen').text
    r = lab.end(kind='decision',choice='necessary_only').json()['registration']
    assert [i['status'] for i in r['items']] == ['deferred','refused'] and r['submitted'] == ['project_experience']
    assert [(e['status'], e['quote']) for e in r['history']] == [('submitted',project),('refused',city),('deferred',last)]


@pytest.mark.parametrize('failure',['intent_only','other_fields_value','unsupported','unsafe'])
def test_unverified_item_changes_never_commit(lab, failure):
    model = propose(lab)
    text = {'intent_only':'我可以提供项目经历', 'other_fields_value':'项目经历：虚构城市 B'}.get(failure,'项目经历：虚构项目 A')
    model.actions = [action('respond_registration','none',text,field='project_experience',status='submitted')]
    model.body = '我收到了项目经历。'
    if failure == 'unsupported': model.supported = []
    if failure == 'unsafe': model.safe = False
    before = lab.snap()
    assert 'event: error' in lab.post(text,'chen').text
    after = lab.snap()
    assert after['registration'] == before['registration'] and after['messages'] == before['messages']


def test_uninvited_and_other_contacts_cannot_change_registration(lab):
    text = '项目经历可以给'
    choice = action('respond_registration','none',text,field='project_experience',status='agreed')
    lab.model.actions, lab.model.disclosures, lab.model.body = [choice], [], '我们可以先聊岗位。'
    assert 'event: done' in lab.post(text,'chen').text
    assert not lab.snap()['registered']
    propose(lab)
    lab.model.actions, lab.model.body = [choice], '我只介绍自己的岗位。'
    assert 'event: done' in lab.post(text,'lin').text
    assert all(i['status'] is None for i in lab.snap()['registration']['items'])


def test_semantic_adapter_payload_is_role_scoped_and_not_resolved_on_client(lab, monkeypatch):
    import asyncio
    import httpx
    monkeypatch.setenv('OPENAI_BASE_URL','http://127.0.0.1:12345/v1')
    adapter = CompatibleModel(); captured=[]
    async def post(self,url,**opts):
        captured.append(opts['json']);return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':json.dumps({'body':'这只是当前角色的回答。'},ensure_ascii=False)}}]})
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    reply = asyncio.run(adapter.reply('wang',[],ASK,{'K05':'本人没有核实。'},False))
    context = json.loads(captured[0]['messages'][1]['content'])
    assert reply.body == '这只是当前角色的回答。' and context['private_history'] == []
    assert set(context['permitted_facts']) == {'K05'}
    assert context['character']['name'] == '王宇' and '陈浩' not in json.dumps(context['character'], ensure_ascii=False)
