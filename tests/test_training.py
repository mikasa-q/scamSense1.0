import json
from concurrent.futures import ThreadPoolExecutor
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
from backend.policy import Action, Analysis, Audit, ChenAnalysis, ChenAudit, Disclosure, Reply

ASK = '你亲自核实过这个岗位吗？'
ANSWER = '我在校园群里看到转发，没亲自核实。'
JUDGE = '群里转发不能证明招聘方获得了授权。'
DENIAL = 'self_denies_job_check'

def labels(*kinds):
    return [{'part_id':i, 'kind':kind} for i, kind in enumerate(kinds)]

def action(kind, focus, quote, source='own', **attrs):
    return Action(kind=kind, focus=focus, quote=quote, source=source, **attrs)

class ScriptedModel:
    configured = True
    def __init__(self):
        self.actions = [action('verify_friend','K05',ASK)]
        self.body = ANSWER
        self.k05 = labels('origin', DENIAL)
        self.k04 = 'none'
        self.disclosures = []
        self.supported = None
        self.safe = True
        self.break_at = None
        self.reg = None
        self.received = []
        self.previously_received = []
        self.reply_availability = 'unstated'
        self.calls = []
    async def analyze(self, role, history, text, registration):
        self.calls.append(('analysis',role,history,text))
        if self.break_at == 'analysis': raise RuntimeError()
        if role == 'chen':
            return ChenAnalysis(actions=self.actions)
        return Analysis(actions=self.actions)
    async def reply(self, role, history, text, facts, invite, registration):
        self.calls.append(('reply',role,history,dict(facts),invite))
        if self.break_at == 'reply': raise RuntimeError()
        return Reply(body=self.body)
    async def audit(self, role, history, text, facts, invite, actions, body, registration):
        self.calls.append(('audit',role,history,dict(facts),invite))
        if self.break_at == 'audit': raise RuntimeError()
        evidence = dict(safe=self.safe, k04=self.k04, supported=list(range(len(actions))) if self.supported is None else self.supported, disclosures=self.disclosures, registration_quote=self.reg)
        if role == 'chen':
            return ChenAudit(**evidence, received_now=self.received, previously_received=self.previously_received,
                             reply_availability=self.reply_availability)
        return Audit(**evidence, k05=self.k05 if role == 'wang' else None)

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
    lab.model.k05 = labels('other', 'other')
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

@pytest.mark.parametrize(('question','reply','kinds'), [
    ('你从哪看到的？', '校园群里有人转发过。', ('origin',)),
    ('是从学校官网吗？', '没有，群里看到的。', ('origin','origin')),
], ids=['source-only','short-no-about-channel'])
@pytest.mark.parametrize('overclaims',[True,False])
def test_source_only_is_not_k05(lab, question, reply, kinds, overclaims):
    lab.model.actions = [action('verify_friend','K05',question)]
    lab.model.body, lab.model.k05 = reply, labels(*kinds)
    lab.model.disclosures = [Disclosure(focus='K05', quote=reply)] if overclaims else []
    assert 'event: done' in lab.post(question).text
    user, wang = lab.snap()['messages']
    assert wang['body'] == reply
    r = lab.end(kind='early').json()
    assert r['disclosures'] == [] and report_dims(r)['risk']['evidence'] == []
    assert report_dims(r)['verify']['evidence'][0]['message_id'] == user['id']

@pytest.mark.parametrize(('reply','kinds'), [
    ('没有，我只看了群转发，没跟招聘方打过交道。', (DENIAL,'origin',DENIAL)),
    ('没有，群里看到的。', (DENIAL,'origin')), ('没有', (DENIAL,)), ('没', (DENIAL,)),
], ids=['contextual','short-no-about-check','bare-no','single-character'])
def test_k05_contextual_denial_links_only_to_wangs_reply(lab, reply, kinds):
    question = '你亲自核实过吗？'
    lab.model.actions = [action('verify_friend','K05',question)]
    lab.model.body, lab.model.k05 = reply, labels(*kinds)
    assert 'event: done' in lab.post(question).text
    report = lab.end(kind='early').json()
    snap = lab.snap()
    assert snap['review'] == report
    user, wang = snap['messages']
    ref, = report['disclosures']
    assert wang['body'] == reply
    assert (ref['focus'], ref['role'], ref['speaker'], ref['message_id'], ref['quote']) == ('K05', 'wang', 'assistant', wang['id'], reply)
    assert report_dims(report)['verify']['evidence'][0]['message_id'] == user['id']
    assert report_dims(report)['risk']['evidence'] == []

@pytest.mark.parametrize(('reply','kinds'), [
    ('群里有人转发，我没问清楚源头。', ('origin','origin')),
    ('我不知道转发的人有没有亲自核实。', ('other_person',)),
    ('发给我的同学没亲自核实。', ('other_person',)), ('那条消息我已经问过招聘方了。', ('other',)),
    ('我记不清有没有核实过了', ('uncertain',)),
    ('好像没有核实过。\n仔细想想，我也记不清了。', ('uncertain','other','uncertain')),
], ids=['origin','unknown-other-person','other-person','did-check','uncertain','later-qualification'])
def test_k05_does_not_transfer_uncertainty_or_another_speakers_denial(lab, reply, kinds):
    lab.model.body, lab.model.k05 = reply, labels(*kinds)
    lab.model.disclosures = [Disclosure(focus='K05',quote=reply)]
    assert 'event: done' in lab.post().text
    assert lab.snap()['messages'][1]['body'] == reply
    report = lab.end(kind='early').json()
    assert report['disclosures'] == [] and not report_dims(report)['risk']['evidence']

@pytest.mark.parametrize(('reply','kinds'), [
    ('群里转发的，但我跟招聘方没打过交道。', ('origin',DENIAL)),
    ('我在校园群看到的，当时觉得挺有意思的，但没去查真伪。', ('origin','other',DENIAL)),
    ('我记不清在哪个群看的。\n不过这条转发，我确实没跟招聘方核实。', ('origin','other',DENIAL)),
], ids=['mixed','mixed-with-aside','uncertainty-about-channel-only'])
def test_source_question_cannot_hide_an_unsolicited_denial(lab, reply, kinds):
    question = '你从哪看到的？'
    lab.model.actions = [action('verify_friend','K05',question)]
    lab.model.body, lab.model.k05 = reply, list(reversed(labels(*kinds)))
    assert 'event: done' in lab.post(question).text
    disclosure, = lab.end(kind='early').json()['disclosures']
    assert disclosure['quote'] == reply and disclosure['message_id'] == lab.snap()['messages'][1]['id']

def assert_k05_turn_rejected(lab, result):
    assert 'event: error' in result.text and 'event: done' not in result.text
    snap = lab.snap()
    assert snap['messages'] == [] and not snap['busy'] and snap['stage'] == 0
    with lab.app.state.factory() as db:
        assert list(db.scalars(select(Receipt.status))) == ['failed']
        assert list(db.scalars(select(Trace.id))) == []
        assert list(db.scalars(select(StoryEvent.kind))) == ['created']
    assert lab.end(kind='early').json()['disclosures'] == []

@pytest.mark.parametrize('ids', [
    (-1,1), (0,2), (1,1), (0,1,1), (1,), (0,), (), (0,True), ('0',1), (0.0,1),
], ids=['negative','out-of-range','duplicate','extra-duplicate','omitted-with-positive',
        'omitted-with-negative','empty','boolean','string','float'])
def test_k05_requires_each_backend_part_id_exactly_once(lab, ids):
    lab.model.k05 = [{'part_id':i, 'kind':'origin' if i == 0 else DENIAL} for i in ids]
    assert_k05_turn_rejected(lab, lab.post())

@pytest.mark.parametrize('failure', ['question_quote','missing_id','blank_quote','missing_assessment','not_permitted','wrong_role'])
def test_k05_invalid_attribution_never_commits_a_turn(lab, failure):
    if failure == 'question_quote': lab.model.k05 = [{'kind':DENIAL,'quote':ASK}]
    if failure == 'missing_id': lab.model.k05 = [{'kind':DENIAL}]
    if failure == 'blank_quote': lab.model.k05 = [{'kind':DENIAL,'quote':' '}]
    if failure == 'wrong_role': lab.model.disclosures = [Disclosure(focus='K05',quote=ANSWER)]
    if failure == 'missing_assessment': lab.model.k05 = None
    if failure == 'not_permitted': lab.model.actions = []
    assert_k05_turn_rejected(lab, lab.post(role='lin' if failure == 'wrong_role' else 'wang'))

@pytest.mark.parametrize('finding', [
    {'kind':'self_denies_job_check', 'quote':'没有核实过'},
    {'part_id':0, 'kind':'self_denies_job_check', 'quote':'没有核实过'},
], ids=['free-quote', 'id-plus-free-quote'])
def test_k05_rejects_clipped_uncertain_quote(lab, finding):
    lab.model.body = '我记不清有没有核实过了'
    lab.model.k05 = [finding]
    assert_k05_turn_rejected(lab, lab.post())

@pytest.mark.parametrize('kind', ['uncertain', DENIAL])
def test_k05_generic_disclosure_cannot_supply_a_clipped_quote(lab, kind):
    lab.model.body, lab.model.k05 = '我记不清有没有核实过了', labels(kind)
    lab.model.disclosures = [Disclosure(focus='K05', quote='没有核实过')]
    assert_k05_turn_rejected(lab, lab.post())

@pytest.mark.parametrize(('reply','kinds'), [
    ('我也不确定，可能没有核实过。', ('uncertain',DENIAL)),
    ('没有。\n其实我记不清自己问过没有了。', (DENIAL,'uncertain')),
], ids=['qualification-before','qualification-after'])
def test_k05_conflicting_labels_cannot_drop_a_qualification(lab, reply, kinds):
    lab.model.body, lab.model.k05 = reply, labels(*kinds)
    assert_k05_turn_rejected(lab, lab.post())

@pytest.mark.parametrize(('role', 'body', 'generic_quote'), [
    ('lin', '我们一般用官方邮箱发通知。', '官方邮箱'),
    ('lin', '你可以相信我。', '相信我'),
    ('chen', '我不清楚有没有对应的公告。', '公告'),
    ('chen', '朋友只说是转发来的。', '转发'),
    ('chen', '对方说没有编号，我自己并不清楚。', '没有编号'),
    ('chen', '我手里没有。等等，我其实不确定说的是不是这条转发。', '我手里没有'),
])
def test_k04_non_disclosure_keeps_question_and_normal_reply(lab, role, body, generic_quote):
    question = '这次能从哪里独立核对？'
    lab.model.actions = [action('verify_official', 'K04', question)]
    lab.model.body = body
    lab.model.disclosures = [Disclosure(focus='K04', quote=generic_quote)]
    assert 'event: done' in lab.post(question, role).text
    assert [m['body'] for m in lab.snap()['messages']] == [question, body]
    report = lab.end(kind='early').json()
    assert not report['disclosures']
    dims = report_dims(report)
    assert [e['quote'] for e in dims['verify']['evidence']] == [question]
    assert not dims['risk']['evidence'] and not dims['sources']['evidence']


@pytest.mark.parametrize(('role', 'ask', 'body', 'finding', 'quote'), [
    ('lin', True, '请从公司公开招聘栏目核对我负责的面试。', 'k04_interview_route', '我没说过这句话'),
    ('lin', False, '请从公司公开招聘栏目核对我负责的面试。', 'k04_interview_route', None),
    ('lin', True, '平时我用邮箱联系。', None, '邮箱'),
    ('chen', True, '可从公司官网联系招聘团队核对我负责的面试。', 'k04_interview_route', None),
    ('lin', True, '我没有核对这条转发的官方编号。', 'k04_missing_reference', None),
    ('wang', True, '这条转发可以直接从企业招聘渠道得到确认。', 'k04_interview_route', None),
    ('lin', True, '你可以查我负责的面试；陈浩的转发也已经由我证实了。', 'unsupported_claim', None),
    ('chen', True, '没有编号，可见这就是假消息。', 'unsupported_claim', None),
], ids=['foreign-quote', 'unpermitted', 'missing-assessment', 'wrong-guide-owner', 'wrong-gap-owner', 'friend', 'endorsement', 'false-verdict'])
def test_k04_invalid_or_misleading_reply_writes_nothing(lab, role, ask, body, finding, quote):
    text = '这条转发能从哪里独立核实？' if ask else '你好。'
    lab.model.actions = [action('verify_official', 'K04', text)] if ask else []
    lab.model.body, lab.model.k04 = body, finding
    lab.model.k05 = labels('other')
    if quote:
        lab.model.disclosures = [Disclosure(focus='K04', quote=quote)]
    assert 'event: error' in lab.post(text, role).text
    assert lab.snap()['messages'] == []
    report = lab.end(kind='early').json()
    assert not report['disclosures'] and not any(d['evidence'] for d in report['dimensions'])


@pytest.mark.parametrize('reply_uses_fact', [False, True])
def test_k04_retelling_cannot_unlock_a_fact_or_become_user_judgment(lab, reply_uses_fact):
    text = '同学说他问过哪里能独立核实，还说暂时没有官方依据。'
    lab.model.actions = [action('verify_official', 'K04', '哪里能独立核实'),
                         action('identify_gap', 'K04', '暂时没有官方依据')]
    lab.model.supported = []
    lab.model.body = '目前我没有这条转发的官方公告可供独立核实。' if reply_uses_fact else '明白，这是你转述同学的说法。'
    lab.model.k04 = 'k04_missing_reference' if reply_uses_fact else 'none'
    result = lab.post(text, 'chen').text
    assert ('event: error' if reply_uses_fact else 'event: done') in result
    report = lab.end(kind='early').json()
    assert not report['disclosures'] and not any(d['evidence'] for d in report['dimensions'])


@pytest.mark.parametrize('disclose_again', [False, True], ids=['continue-and-finish', 'new-route'])
def test_pre_k04_excerpt_neither_grants_permission_nor_enters_new_review(lab, disclose_again):
    from backend.db import Message
    question, old_body = '能从哪里独立核对？', '我们一般用官方邮箱发通知。'
    factory = lab.app.state.factory
    with factory.begin() as db:
        receipt = Receipt(sid=lab.sid, request_id=str(uuid4()), fingerprint=training.digest('lin\0' + question),
                          attempt=uuid4().hex, status='done')
        db.add(receipt); db.flush()
        user, lin = [Message(sid=lab.sid, receipt=receipt.id, role='lin', speaker=speaker, body=body)
                     for speaker, body in [('user', question), ('assistant', old_body)]]
        db.add_all([user, lin]); db.flush()
        db.add_all([Trace(sid=lab.sid, message_id=user.id, kind='verify_official', focus='K04', quote=question, why='核实提问'),
                    Trace(sid=lab.sid, message_id=lin.id, kind='disclosure', focus='K04', quote='官方邮箱', why='角色披露'),
                    StoryEvent(sid=lab.sid, message_id=user.id, stage=4, kind='verify_official')])
        db.get(Training, lab.sid).stage = 4
    lab.model.actions, lab.model.body = [], '可以继续聊。'
    assert 'event: done' in lab.post('你好。', 'lin').text
    assert lab.model.calls[-2][2] == [{'speaker':'user','text':question}, {'speaker':'assistant','text':old_body}]
    assert lab.model.calls[-2][3] == {} and lab.model.calls[-1][3] == {}
    expected = []
    if disclose_again:
        lab.model.actions = [action('verify_official', 'K04', question)]
        lab.model.body, lab.model.k04 = '请通过公司公开招聘渠道核对我负责的面试。', 'k04_interview_route'
        assert 'event: done' in lab.post(question, 'lin').text
        assert training.private_context(factory, lab.sid, 'lin')[1] == {'K04'}
        expected.append((lab.snap()['messages'][-1]['id'], lab.model.body))
    report = lab.end(kind='early').json()
    assert [(e['message_id'], e['quote']) for e in report['disclosures']] == expected
    assert report_dims(report)['verify']['evidence'][0]['message_id'] == user.id
    assert lab.snap()['messages'][1]['body'] == old_body
    with factory() as db:
        trace = db.scalars(select(Trace).where(Trace.message_id == lin.id)).one()
        assert (trace.focus, trace.kind, trace.quote) == ('K04', 'disclosure', '官方邮箱')


def test_archived_k04_report_is_read_as_saved_not_reclassified(lab):
    from backend.db import Review
    body = '我们一般用官方邮箱发通知。'
    lab.model.actions, lab.model.body = [], body
    assert 'event: done' in lab.post('平时怎样联系？', 'lin').text
    mid = lab.snap()['messages'][-1]['id']
    original = lab.end(kind='early').json()
    ref = dict(role='lin', speaker='assistant', message_id=mid, focus='K04', topic='可独立核对的官方依据',
               quote='官方邮箱', why='这段角色原话实际披露了该事实；不计作你的识别证据。')
    original.update(rubric='evidence-only-v1', disclosures=[ref])
    with lab.app.state.factory.begin() as db:
        db.add(Trace(sid=lab.sid, message_id=mid, kind='disclosure', focus='K04', quote=ref['quote'], why=ref['why']))
        review = db.get(Review, lab.sid)
        review.rubric, review.payload = original['rubric'], original
    calls = len(lab.model.calls)
    assert lab.snap()['review'] == lab.end(kind='early').json() == original
    assert len(lab.model.calls) == calls
    with lab.app.state.factory() as db:
        assert db.get(Review, lab.sid).payload == original


@pytest.mark.parametrize(('focus', 'kind', 'question', 'answer'), [
    ('K01', 'ask_employer', '能出示企业的招聘授权吗？', '我不能出示可独立核对的企业招聘授权。'),
    ('K02', 'ask_data', '为什么初筛要收简历以外的资料？', '说是汇总意向和安排面试，但我说不清初筛为什么要这些资料。'),
    ('K03', 'ask_data', '谁接收资料、保存多久，会交给第三方吗？', '资料的实际接收方、保存期限和第三方处理方式，我都说不清。'),
])
def test_consultant_question_is_not_a_disclosure_or_a_user_judgment(lab, focus, kind, question, answer):
    lab.model.actions = [action(kind, focus, question)]
    lab.model.body = '这方面我们之后再聊。'
    assert 'event: done' in lab.post(question, 'chen').text
    assert not training.private_context(lab.app.state.factory, lab.sid, 'chen')[1]
    lab.model.body, lab.model.disclosures = answer, [Disclosure(focus=focus, quote=answer)]
    assert 'event: done' in lab.post(question, 'chen').text
    msgs = lab.snap()['messages']
    report = lab.end(kind='early').json()
    ref, = report['disclosures']
    assert (ref['focus'], ref['speaker'], ref['message_id'], ref['quote']) == (focus, 'assistant', msgs[3]['id'], answer)
    dims = report_dims(report)
    assert [e['message_id'] for e in dims['verify']['evidence']] == [msgs[0]['id'], msgs[2]['id']]
    assert not dims['risk']['evidence'] and not dims['sources']['evidence']


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
    lab.model.k05 = labels('other')
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

def test_failure_diagnostics_do_not_expose_chat_or_token(lab, caplog):
    from sqlalchemy import exc, text
    private = '这是仅用于验证日志边界的一段虚构草稿。'
    lab.model.break_at = 'reply'
    with caplog.at_level('INFO'):
        assert 'event: error' in lab.post(private).text
    assert private not in caplog.text and lab.hdr['Authorization'].split()[1] not in caplog.text
    with lab.app.state.engine.connect() as conn, pytest.raises(exc.DBAPIError) as failure:
        conn.execute(text('SELECT :draft FROM absent_test_table'), {'draft':private})
    assert private not in str(failure.value)


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
    with pytest.raises(ValueError): training.store_turn(factory,lab.sid,receipt,expired,'wang',ASK,ANSWER,[],{},None,False,{})
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
    model.k05 = labels('other')
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
    project, city = '项目经历我愿意给', '我拒绝提供所在城市'
    model.actions = [action('respond_registration','none',project,field='project_experience',status='agreed'),
                     action('respond_registration','none',city,field='city',status='refused')]
    model.body = '城市不必提供，项目经历由你自己决定是否确认提交。'
    assert 'event: done' in lab.post(project+'，'+city,'chen').text
    assert lab.snap()['registration']['submitted'] == []
    assert confirm(lab).status_code == 200
    r = lab.snap()['registration']
    assert [i['status'] for i in r['items']] == ['agreed','refused'] and r['submitted'] == ['project_experience']
    last = '项目经历之后先不提供。'
    model.actions = [action('respond_registration','none',last,field='project_experience',status='deferred')]
    model.body = '可以，不需要继续给项目资料。'
    assert 'event: done' in lab.post(last,'chen').text
    r = lab.end(kind='decision',choice='necessary_only').json()['registration']
    assert [i['status'] for i in r['items']] == ['deferred','refused'] and r['submitted'] == ['project_experience']
    assert [(e['source'], e.get('quote', e.get('value'))) for e in r['history']] == [
        ('chat',project), ('chat',city), ('explicit','虚构项目 A'), ('chat',last)]
    assert lab.snap()['registration']['history'] == r['history']


@pytest.mark.parametrize('first,first_status,last,last_status', [
    ('所在城市可以给', 'agreed', '所在城市先不提供', 'deferred'),
    ('我先不提供所在城市', 'deferred', '我拒绝继续提供所在城市', 'refused'),
])
def test_same_turn_corrections_follow_the_source_not_candidate_order(lab, first, first_status, last, last_status):
    model = propose(lab)
    earlier = action('respond_registration', 'none', first, field='city', status=first_status)
    later = action('respond_registration', 'none', last, field='city', status=last_status)
    model.actions, model.body = [later, earlier, earlier], '明白，按你最后说的办。'
    text, rid = first + '。算了，' + last, str(uuid4())
    assert 'event: done' in lab.post(text, 'chen', rid).text
    assert '"cached":true' in lab.post(text, 'chen', rid).text
    snap = lab.snap()
    city = next(i for i in snap['registration']['items'] if i['key'] == 'city')
    assert (city['status'], city['quote']) == (last_status, last)
    r = lab.end(kind='early').json()['registration']
    assert r['items'] == snap['registration']['items'] and r['submitted'] == []
    assert [(e['status'], e['quote']) for e in r['history']] == [(first_status, first), (last_status, last)]
    assert all((e['message_id'], e['reply_id']) == tuple(m['id'] for m in snap['messages'][-2:]) for e in r['history'])


def test_repeated_quote_needs_a_verified_position(lab):
    model = propose(lab)
    yes, no = '所在城市可以给', '所在城市先不提供'
    text = f'{yes}。{no}。{yes}'
    def city(quote, status, **attrs):
        return action('respond_registration', 'none', quote, field='city', status=status, **attrs)
    model.body = '明白，最后是愿意给，但还没有提交。'
    for ambiguous in [city(yes, 'agreed'), city(yes, 'agreed', position=1)]:
        model.actions = [ambiguous]
        before = lab.snap()
        assert 'event: error' in lab.post(text, 'chen').text and lab.snap() == before
    model.actions = [city(yes, 'agreed', position=text.rindex(yes)), city(no, 'deferred'), city(yes, 'agreed', position=0)]
    assert 'event: done' in lab.post(text, 'chen').text
    r = lab.end(kind='early').json()['registration']
    assert [e['quote'] for e in r['history']] == [yes, no, yes]
    assert r['submitted'] == [] and r['items'][1]['status'] == 'agreed'


@pytest.mark.parametrize('previous_invitation', [False, True])
def test_only_explicit_audited_reopening_overrides_whole_decline(lab, previous_invitation):
    model = propose(lab) if previous_invitation else lab.model
    stop, interest, resume = '我拒绝整个登记。', '我对你的岗位仍然感兴趣。', '我改主意了，现在想登记'
    model.actions, model.disclosures, model.body = [action('decline', 'none', stop)], [], '好的，不再邀请你登记。'
    assert 'event: done' in lab.post(stop, 'chen').text
    model.actions = [action('interest', 'none', interest, opportunity='chen')]
    model.body = '可以继续了解这个岗位。'
    assert 'event: done' in lab.post(interest, 'chen').text and not model.calls[-2][-1]
    model.actions = [action('resume_registration', 'none', resume)]
    model.body = '好的，登记已恢复。' if previous_invitation else '好的，可以继续聊岗位。'
    model.reply_availability = 'open' if previous_invitation else 'unstated'
    model.reg = None
    before = lab.snap()
    model.supported = []
    assert 'event: error' in lab.post(resume, 'chen').text and lab.snap() == before
    model.supported = None
    assert 'event: done' in lab.post(resume, 'chen').text and not model.calls[-2][-1]
    assert not training.private_context(lab.app.state.factory, lab.sid, 'chen')[2]['declined_all']
    model.actions, model.reg, model.body = [action('interest', 'none', interest, opportunity='chen')], None, '我们继续聊岗位。'
    assert 'event: done' in lab.post(interest, 'chen').text and model.calls[-2][-1] is (not previous_invitation)
    assert lab.snap()['registered'] is previous_invitation
    r = lab.end(kind='early').json()['registration']
    assert r['submitted'] == [] and [e['quote'] for e in r['references'] if e['speaker'] == 'user'] == [stop, resume]


@pytest.mark.parametrize('claim', ['project_experience','unspecified'])
def test_falsely_acknowledged_chat_is_not_persisted_even_if_supported(lab, claim):
    model = propose(lab)
    text = '项目经历：虚构项目 A，多谢！'
    model.actions = [action('respond_registration','none',text,field='project_experience',status='submitted')]
    model.body, model.received = '资料已经收到了。', [claim]
    before = lab.snap()
    response = lab.post(text,'chen').text
    assert 'event: error' in response and model.body not in response and lab.snap() == before
    model.body, model.received, model.previously_received = '你之前已经交过了。', [], [claim]
    assert 'event: error' in lab.post(text,'chen').text and lab.snap() == before


@pytest.mark.parametrize(('text', 'source'), [
    ('陈老师，下午好！', None), ('城市那栏是填「虚构城市 B」吗？', 'uncertain'),
    ('我只是在引用同学的原话：「我提交的项目经历：虚构项目 A」。', 'retold'),
], ids=['just-a-greeting', 'question', 'quotation'])
def test_non_submitting_speech_can_continue_after_invitation(lab, text, source):
    model = propose(lab)
    field = 'city' if source == 'uncertain' else 'project_experience'
    model.actions = [action('respond_registration', 'none', text, source, field=field, status='submitted')] if source else []
    model.body, model.received = '我们可以继续聊。', []
    assert 'event: done' in lab.post(text, 'chen').text
    snap = lab.snap()
    assert snap['registration']['history'] == snap['registration']['submitted'] == []
    assert snap['messages'][-1]['body'] == model.body


@pytest.mark.parametrize(('option','extra'), [('city',{}), ('虚构城市 B',{}), ('city_b',{'value':'另一座城市'}),
                                          ('project_a',{'field':'city'}), ('city_b',{'text':'虚构城市 B'}),
                                          ('city_b',{'role':'chen'}), (None,{})])
def test_confirmation_accepts_only_a_fixed_option(lab, option, extra):
    propose(lab)
    before = lab.snap()
    assert confirm(lab, option, **extra).status_code == 422
    assert lab.snap() == before


def test_confirmation_checks_owner_contact_invitation_busy_and_closed(lab):
    assert confirm(lab).status_code == 409
    propose(lab)
    before = lab.snap()
    path = lab.path + '/contacts/chen/registration/confirm'
    other = lab.client.post('/api/sessions').json()
    for url, hdr, code in [(path, {}, 401), (path, {'Authorization':'Bearer '+other['token']}, 404),
                           (path.replace(lab.sid,other['id']), lab.hdr, 404)]:
        assert lab.client.post(url, headers=hdr, json={'option_id':'city_b'}).status_code == code
    for role in ['lin','wang']:
        assert confirm(lab, contact=role).status_code == 403
    rid, attempt = training.reserve(lab.app.state.factory,lab.sid,str(uuid4()),'chen','我要停止登记',True)
    assert confirm(lab).status_code == 409
    training.fail_turn(lab.app.state.factory,lab.sid,rid,attempt)
    assert lab.snap() == before
    report = lab.end(kind='decision', choice='necessary_only').json()
    assert confirm(lab).status_code == 409 and lab.snap()['review'] == report
    assert report['registration']['history'] == []


def stop_registration(lab):
    model = propose(lab)
    stop = '我要停止整个预登记。'
    model.actions, model.body = [action('decline','none',stop)], '明白，预登记已停止。'
    assert 'event: done' in lab.post(stop, 'chen').text
    return model


@pytest.mark.parametrize('support_resume', [False, True])
def test_same_turn_resume_only_authorizes_later_items(lab, support_resume):
    model = stop_registration(lab)
    early, resume, late = '项目经历我愿意给', '我明确重新开始整个登记', '所在城市先不提供'
    model.actions = [action('respond_registration','none',late,field='city',status='deferred'),
                     action('resume_registration','none',resume),
                     action('respond_registration','none',early,field='project_experience',status='agreed')]
    model.body, model.reply_availability = '已恢复，城市这一项可以暂缓。', 'open'
    model.supported = [0,1,2] if support_resume else [0,2]
    before = lab.snap()
    result = lab.post('。'.join([early,resume,late]), 'chen')
    if not support_resume:
        assert 'event: error' in result.text and lab.snap() == before
        return
    assert 'event: done' in result.text
    state = lab.snap()['registration']
    assert not state['declined_all'] and state['submitted'] == []
    assert [(e['field'],e['quote']) for e in state['history']] == [('city',late)]


@pytest.mark.parametrize(('body','stance'), [('之前已经停止，不能继续登记。','stopped'),
    ('必须先重新邀请你。','not_invited'), ('明白。','unstated'), ('恢复了，但不能继续登记。','conflicting')])
def test_resume_and_reply_must_agree_before_either_is_saved(lab, body, stance):
    model = stop_registration(lab)
    text = '我明确要重新开始登记。'
    model.actions = [action('resume_registration','none',text)]
    model.body, model.reply_availability = body, stance
    before = lab.snap()
    assert 'event: error' in lab.post(text,'chen').text and lab.snap() == before
    assert confirm(lab,'city_b').status_code == 409
    model.body, model.reply_availability = '登记已恢复，可以继续。', 'open'
    assert 'event: done' in lab.post(text,'chen').text
    snap = lab.snap()
    assert not snap['registration']['declined_all'] and snap['registration']['history'] == []
    assert snap['messages'][-1]['body'] == model.body and not model.calls[-2][-1]
    assert confirm(lab,'city_b').json()['registration']['submitted'] == ['city']


def test_same_turn_stop_blocks_later_field_and_false_receipt_is_not_saved(lab):
    model = propose(lab)
    stop, field = '不再参与整个登记', '我提交的项目经历：虚构项目 A'
    model.actions = [action('respond_registration', 'none', field, field='project_experience', status='submitted'), action('decline', 'none', stop)]
    model.body, model.received = '已停止，不过已收到项目经历。', ['project_experience']
    before = lab.snap()
    assert 'event: error' in lab.post(stop+'。'+field, 'chen').text and lab.snap() == before
    model.body, model.received = '已停止，本次没有收取资料。', []
    assert 'event: done' in lab.post(stop+'。'+field, 'chen').text
    state = lab.snap()['registration']
    assert state['declined_all'] and state['history'] == state['submitted'] == []


def test_future_promise_with_exact_placeholder_is_not_a_submission(lab):
    model = propose(lab)
    text = '以后我会给虚构项目 A'
    model.actions = [action('respond_registration','none',text,field='project_experience',status='submitted')]
    model.supported, model.body, model.received = [], '收到项目资料了。', ['project_experience']
    before = lab.snap()
    assert 'event: error' in lab.post(text,'chen').text and lab.snap() == before
    model.actions = [action('respond_registration','none',text,field='project_experience',status='agreed')]
    model.supported, model.body, model.received = [0], '明白，现在不需要提供。', []
    assert 'event: done' in lab.post(text,'chen').text
    state = lab.snap()['registration']
    assert state['items'][0]['status'] == 'agreed' and state['submitted'] == []


@pytest.mark.parametrize(('text','source'), [('同学说他要重新开始整个登记。','retold'), ('我是否要重启登记？','uncertain')])
def test_retold_and_uncertain_resumes_do_not_reopen(lab, text, source):
    model = stop_registration(lab)
    model.actions = [action('resume_registration','none',text,source)]
    model.body = '不必办理登记。'
    assert 'event: done' in lab.post(text,'chen').text
    assert lab.snap()['registration']['declined_all']


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


def confirm(lab, option='project_a', contact='chen', **extra):
    return lab.client.post(f'{lab.path}/contacts/{contact}/registration/confirm', headers=lab.hdr,
                           json={'option_id':option, **extra})


@pytest.mark.parametrize(('field','text'), [('project_experience','项目经历：虚构项目 A，多谢！'),
                                          ('city','我现在提交所在城市：虚构城市 B。')])
def test_chat_cannot_collect_even_with_a_supported_submission(lab, field, text):
    model = propose(lab)
    model.actions = [action('respond_registration', 'none', text, field=field, status='submitted')]
    model.body = '还没有提交；如果你愿意，可以点对应的确认按钮。'
    assert 'event: done' in lab.post(text, 'chen').text
    snap = lab.snap()
    assert snap['registration']['submitted'] == snap['registration']['history'] == []
    assert [m['body'] for m in snap['messages'][-2:]] == [text, model.body]


def test_confirmation_is_idempotent_and_model_independent(lab):
    model = propose(lab)
    before = lab.snap(); calls = len(model.calls)
    model.configured = False
    for option, field, value in [('project_a','project_experience','虚构项目 A'), ('city_b','city','虚构城市 B')]:
        res = confirm(lab, option)
        assert res.status_code == 200
        state = res.json()['registration']
        assert confirm(lab, option).json()['registration'] == state
        entry = state['history'][-1]
        assert (entry['field'], entry['value'], entry['status'], entry['source']) == (field, value, 'submitted', 'explicit')
        assert not any(entry.get(k) for k in ('quote','message_id','reply_id','reply_quote'))
    snap = lab.snap()
    assert len(model.calls) == calls and snap['messages'] == before['messages']
    assert len(snap['registration']['history']) == 2 and snap['registration']['submitted'] == ['project_experience','city']
    assert all(i['status'] is None for i in snap['registration']['items'])


def test_parallel_confirmation_retries_record_one_click(lab):
    propose(lab)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: confirm(lab,'city_b').status_code, range(4))) == [200]*4
    entry, = lab.snap()['registration']['history']
    assert (entry['source'],entry['value']) == ('explicit','虚构城市 B')


def test_chat_writer_cannot_insert_a_model_submission(lab):
    propose(lab)
    factory = lab.app.state.factory
    text = '我现在提交所在城市：虚构城市 B。'
    rid, attempt = training.reserve(factory,lab.sid,str(uuid4()),'chen',text,True)
    forged = action('respond_registration','none',text,field='city',status='submitted',position=0)
    before = lab.snap()
    with pytest.raises(ValueError,match='chat can only record willingness'):
        training.store_turn(factory,lab.sid,rid,attempt,'chen',text,'已收到。',[forged],{},None,True,{})
    assert lab.snap() == before
    training.fail_turn(factory,lab.sid,rid,attempt)


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
