import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from backend import training
from backend.db import ROOT, Message, Receipt, RegistrationEntry, Review, StoryEvent, Trace, engine_for
from backend.main import create_app
from backend.model import CHEN_AUDIT, CHEN_GENERATE, CHEN_INTERPRET


OLD_REASON = '保留拒绝意愿，不再主动提出登记。'
SCOPED_REASON = '你明确停止了整个登记，不再主动邀请。'
PROJECT = '我提交的项目经历：虚构项目 A'


def seed_old_session(factory, refusals):
    session = training.create(factory)
    sid = session['id']
    with factory.begin() as db:
        for i, (body, quote, why) in enumerate([('可以自愿预登记。', None, None), *refusals]):
            r = Receipt(sid=sid, request_id=str(uuid4()), fingerprint='old', attempt='old', status='done')
            db.add(r); db.flush()
            msg = Message(sid=sid, receipt=r.id, role='chen', speaker='user' if i else 'assistant', body=body)
            db.add(msg); db.flush()
            if i:
                db.add(Trace(sid=sid, message_id=msg.id, kind='decline', focus='none', quote=quote, why=why))
            else:
                db.add(StoryEvent(sid=sid, message_id=msg.id, kind='registration_proposed', stage=2))
    return session


@pytest.fixture
def upgraded_session(tmp_path, monkeypatch):
    url = f'sqlite:///{(tmp_path / "legacy.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', url)
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('OPENAI_BASE_URL', 'http://127.0.0.1:1/v1')
    def upgrade(refusals, version='0001_training'):
        config = Config(str(ROOT / 'alembic.ini'))
        command.upgrade(config, version)
        engine = engine_for(url)
        s = seed_old_session(sessionmaker(engine, expire_on_commit=False), refusals)
        engine.dispose()
        command.upgrade(config, 'head')
        return '/api/sessions/' + s['id'], {'Authorization':'Bearer ' + s['token']}
    return upgrade


@pytest.fixture
def scopes(monkeypatch):
    votes = {CHEN_INTERPRET:'items_only', CHEN_AUDIT:'items_only'}
    calls = []
    async def post(self, url, **opts):
        system, data = (m['content'] for m in opts['json']['messages'])
        data = json.loads(data); reg = data['registration']; calls.append((system, reg))
        pending = reg.get('legacy_declines', [])
        if system == CHEN_INTERPRET:
            result = {'actions':[dict(kind='respond_registration', focus='none', quote=PROJECT, source='own', field='project_experience', status='submitted')]}
        elif system == CHEN_GENERATE:
            result = {'body':'本次聊天没有收取资料。'}
        else:
            assert system == CHEN_AUDIT
            result = {'safe':True, 'supported':[0], 'registration_quote':None, 'disclosures':[],
                      'received_now':[], 'previously_received':[], 'reply_availability':'unstated'}
        if system in votes and votes[system] is not None:
            result['legacy_scopes'] = {str(p['id']):votes[system] for p in pending}
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices':[{'message':{'content':json.dumps(result)}}]})
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    return votes, calls


def confirm(client, path, headers, option='project_a'):
    return client.post(path+'/contacts/chen/registration/confirm', headers=headers, json={'option_id':option})


def chat(client, path, headers):
    return client.post(path+'/turns', headers=headers, json={'text':PROJECT, 'role':'chen', 'request_id':str(uuid4())}).text


@pytest.mark.parametrize(('version', 'refusals', 'stopped'), [
    ('0001_training', [('我拒绝提供所在城市。', '拒绝提供所在城市', OLD_REASON)], False),
    ('0001_training', [('我停止整个登记。', '停止整个登记', OLD_REASON)], True),
    ('0002_partial_registration', [('所在城市我先不提供。', '先不提供', OLD_REASON)], False),
    ('0002_partial_registration', [('到这里为止吧。', '到这里为止吧', SCOPED_REASON),
                                   ('城市我不提供。', '我不提供', OLD_REASON)], True),
], ids=['old-item', 'old-stop', 'existing-pr-db', 'later-item-cannot-reopen'])
def test_upgrade_keeps_the_correct_gate_on_actual_project_submission(upgraded_session, scopes, version, refusals, stopped):
    path, headers = upgraded_session(refusals, version)
    with TestClient(create_app()) as client:
        before = client.get(path, headers=headers).json()['registration']
        assert not before['scope_pending'] and before['declined_all'] is stopped
        assert 'event: done' in chat(client, path, headers)
        assert not client.get(path, headers=headers).json()['registration']['submitted']
        assert confirm(client, path, headers).status_code == (409 if stopped else 200)
        state = client.get(path, headers=headers).json()['registration']
        assert state['submitted'] == ([] if stopped else ['project_experience'])
        assert state['declined_all'] is stopped
        city = state['items'][1]
        assert city['key'] == 'city' and 'city' not in state['submitted']
        if not stopped:
            expected = 'deferred' if version == '0002_partial_registration' else 'refused'
            assert city['status'] == expected and city['quote'] == refusals[0][1]
        report = client.post(path+'/finish', headers=headers, json={'kind':'early'}).json()['registration']
        assert [r['quote'] for r in report['references']] == [r[1] for r in refusals]
        assert report['submitted'] == state['submitted']


@pytest.mark.parametrize(('body', 'scope', 'accepted'), [
    ('可以谈项目，可住在哪儿这件事我不想跟你说。', 'city_only', True),
    ('我不想给城市；其实这份登记就全部作罢吧。', 'whole', False),
    ('先不用了。', 'uncertain', False),
], ids=['free-form-item', 'whole-message-beats-partial-quote', 'unknown-is-not-consent'])
def test_free_form_legacy_scope_must_be_resolved_from_original_message(upgraded_session, scopes, body, scope, accepted):
    quote = body.split('；')[0] if '；' in body else body
    path, headers = upgraded_session([(body, quote, OLD_REASON)])
    votes, calls = scopes
    votes.update({CHEN_INTERPRET:scope, CHEN_AUDIT:scope})
    with TestClient(create_app()) as client:
        assert client.get(path, headers=headers).json()['registration']['scope_pending']
        assert confirm(client, path, headers).status_code == 409 and not calls
        assert 'event: done' in chat(client, path, headers)
        assert [prompt for prompt, _ in calls] == [CHEN_INTERPRET, CHEN_GENERATE, CHEN_AUDIT]
        for _, context in calls:
            old, = context['legacy_declines']
            assert old['message'] == body and old['quote'] == quote
    with TestClient(create_app()) as fresh:
        assert not fresh.get(path, headers=headers).json()['registration']['submitted']
        assert confirm(fresh, path, headers).status_code == (200 if accepted else 409)
        reg = fresh.get(path, headers=headers).json()['registration']
        assert reg['submitted'] == (['project_experience'] if accepted else [])
        assert reg['declined_all'] is (scope == 'whole') and reg['scope_pending'] is (scope == 'uncertain')
        if scope == 'city_only':
            assert reg['items'][1] == calls[1][1]['items'][1]
            assert reg['items'][1]['status'] == 'refused'


@pytest.mark.parametrize('audit_vote', ['whole', None], ids=['disagrees', 'missing'])
def test_legacy_scope_disagreement_or_missing_vote_keeps_original_evidence(upgraded_session, scopes, audit_vote):
    body = '城里的住处这项就免了吧。'
    path, headers = upgraded_session([(body, body, OLD_REASON)])
    votes, _ = scopes
    with TestClient(create_app()) as client:
        before = client.get(path, headers=headers).json()
        votes[CHEN_AUDIT] = audit_vote
        assert 'event: error' in chat(client, path, headers)
        assert client.get(path, headers=headers).json() == before
        votes[CHEN_AUDIT] = 'items_only'
        assert 'event: done' in chat(client, path, headers)
        assert not client.get(path, headers=headers).json()['registration']['submitted']
        assert confirm(client, path, headers).json()['registration']['submitted'] == ['project_experience']


def test_upgrade_keeps_chat_submissions_distinct_from_clicks(tmp_path, monkeypatch):
    url = f'sqlite:///{(tmp_path / "pr3.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL',url)
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, '0003_legacy_decline_scope')
    engine = engine_for(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    s = seed_old_session(factory, [])
    with factory.begin() as db:
        receipt = Receipt(sid=s['id'], request_id=str(uuid4()), fingerprint='old', attempt='old', status='done')
        db.add(receipt); db.flush()
        user, reply = [Message(sid=s['id'], receipt=receipt.id, role='chen', speaker=speaker, body=body)
                       for speaker,body in [('user',PROJECT), ('assistant','收到了虚构项目 A。')]]
        db.add_all([user, reply]); db.flush()
        db.add(RegistrationEntry(sid=s['id'], message_id=user.id, reply_id=reply.id, position=0,
                                 field='project_experience', status='submitted', quote=PROJECT))
    command.upgrade(config, 'head')
    path, headers = '/api/sessions/'+s['id'], {'Authorization':'Bearer '+s['token']}
    with TestClient(create_app()) as client:
        snap = client.get(path, headers=headers).json()
        old, = snap['registration']['history']
        assert (old['source'],old['status'],old['message_id'],old['reply_id'],old['quote'],old['reply_quote']) == (
            'chat','submitted',user.id,reply.id,user.body,reply.body)
        assert confirm(client,path,headers).json() == snap  # Already submitted under the old contract.
        updated = confirm(client,path,headers,'city_b').json()
        assert updated['messages'] == snap['messages']
        prior, click = updated['registration']['history']
        assert prior == old and (click['source'], click['field'], click['value']) == ('explicit','city','虚构城市 B')
        assert 'quote' not in click and 'reply_id' not in click
        report = client.post(path+'/finish',headers=headers,json={'kind':'early'}).json()
        assert report['registration']['history'] == [old,click]
        assert client.get(path,headers=headers).json()['review'] == report
    with engine.connect() as conn:
        assert conn.execute(text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()


def test_pre_confirmation_review_is_labeled_without_rewriting_its_payload(tmp_path, monkeypatch):
    from backend.db import Ending, Training
    url = f'sqlite:///{(tmp_path / "archived.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL',url)
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, '0003_legacy_decline_scope')
    engine = engine_for(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    s = seed_old_session(factory, [])
    with factory.begin() as db:
        sid = s['id']
        r = Receipt(sid=sid,request_id=str(uuid4()),fingerprint='old',attempt='old',status='done')
        db.add(r); db.flush()
        u = Message(sid=sid,receipt=r.id,role='chen',speaker='user',body=PROJECT)
        a = Message(sid=sid,receipt=r.id,role='chen',speaker='assistant',body='收到了。')
        db.add_all([u,a]); db.flush()
        entry = dict(field='project_experience',status='submitted',message_id=u.id,reply_id=a.id,quote=PROJECT,position=0)
        db.add(RegistrationEntry(sid=sid,**entry))
        original = {'total':None, 'registration':{'history':[dict(**entry, reply_quote=a.body)]}}
        db.add_all([Review(sid=sid,rubric='evidence-only-v1',payload=original), Ending(sid=sid,kind='early',reason='',cited=[])])
        db.get(Training,sid).closed = True
    command.upgrade(config,'head')
    with TestClient(create_app()) as client:
        path, headers = '/api/sessions/'+sid, {'Authorization':'Bearer '+s['token']}
        snap = client.get(path,headers=headers).json()
        assert snap['review']['registration']['history'] == snap['registration']['history'] == [dict(**original['registration']['history'][0],source='chat')]
        assert client.post(path+'/finish',headers=headers,json={'kind':'early'}).json() == snap['review']
        assert confirm(client,path,headers,'city_b').status_code == 409
    with factory() as db:
        assert db.get(Review,sid).payload == original
    engine.dispose()


def test_upgrade_from_main_preserves_sessions_messages_and_saved_review(tmp_path, monkeypatch):
    url = f'sqlite:///{(tmp_path / "existing.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', url)
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, '0001_training')
    engine = engine_for(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    session = training.create(factory)
    sid = session['id']
    previous = training.create(factory)['id']
    with factory.begin() as db:
        receipt = Receipt(sid=sid, request_id=str(uuid4()), fingerprint='legacy', attempt='legacy', status='done')
        db.add(receipt)
        db.flush()
        invite = Message(sid=sid, receipt=receipt.id, role='chen', speaker='assistant', body='可以自愿做虚构预登记。')
        stop = Message(sid=sid, receipt=receipt.id, role='chen', speaker='user', body='我不参加预登记。')
        db.add_all([invite, stop])
        db.flush()
        db.add(StoryEvent(sid=sid, kind='registration_proposed', message_id=invite.id, stage=2))
        db.add(Trace(sid=sid, message_id=stop.id, kind='decline', focus='none', quote=stop.body, why='保留拒绝意愿。'))
        db.add(Review(sid=previous, rubric='evidence-only-v1', payload={'original': '保留旧复盘'}))
    assert 'registration_entries' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory.from_config(config).get_current_head()
        assert conn.execute(text('PRAGMA foreign_key_check')).all() == []
    training.check_access(factory, sid, session['token'])
    snap = training.snapshot(factory, sid)
    assert [(m['id'],m['body']) for m in snap['messages']] == [(invite.id,invite.body),(stop.id,stop.body)]
    assert snap['registered'] and snap['registration']['declined_all']
    assert snap['registration']['history'] == snap['registration']['submitted'] == []
    assert training.snapshot(factory, previous)['review'] == {'original':'保留旧复盘'}
    engine.dispose()
