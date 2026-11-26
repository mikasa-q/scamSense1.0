import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend import training
from backend.classroom import Classroom
from backend.db import ROOT, ClassroomSeat, Training, database_url
from backend.main import create_app, serve
from backend.model import CompatibleModel
from test_training import ASK, ScriptedModel

INVITE = 'test-only-classroom-key-with+slash/and=padding'


def auth(value):
    return {'Authorization': 'Bearer ' + value}


def new(client, code=INVITE):
    return client.post('/api/sessions', headers=auth(code))


def send(client, session, rid=None, text=ASK):
    return client.post('/api/sessions/' + session['id'] + '/turns', headers=auth(session['token']),
                       json={'request_id': rid or str(uuid4()), 'role': 'wang', 'text': text})


@pytest.fixture
def classroom(tmp_path, monkeypatch):
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', f'sqlite:///{(tmp_path / "classroom.db").as_posix()}')
    monkeypatch.setenv('SCAMSENSE_ACCESS_MODE', 'classroom')
    monkeypatch.setenv('SCAMSENSE_CLASS_INVITE', INVITE)
    monkeypatch.setenv('SCAMSENSE_MAX_SESSIONS', '2')
    monkeypatch.setenv('SCAMSENSE_MAX_TURNS', '2')
    monkeypatch.setenv('SCAMSENSE_TURNS_PER_SESSION', '2')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    return ScriptedModel()


def test_class_invitation_only_opens_new_sessions(classroom, monkeypatch):
    with TestClient(create_app(model=classroom)) as client:
        assert client.get('/api/health').json() == {'service':'ScamSense', 'model_configured':True, 'invite_required':True}
        assert client.post('/api/sessions').status_code == new(client, 'not-the-invite').status_code == 403
        first = new(client).json()
        assert new(client, first['token']).status_code == 403
        old_local = training.create(client.app.state.factory)
        assert send(client, old_local).status_code == 403
        assert client.get('/api/sessions/'+first['id'], headers=auth(INVITE)).status_code == 404
        assert client.get('/api/sessions/'+first['id'], headers=auth(old_local['token'])).status_code == 404
    rotated = INVITE[::-1]
    monkeypatch.setenv('SCAMSENSE_CLASS_INVITE', rotated)
    with TestClient(create_app(model=classroom)) as fresh:
        assert new(fresh).status_code == 403
        second = new(fresh, rotated).json()
        assert second['id'] != first['id'] and second['token'] != first['token']
        assert new(fresh, rotated).status_code == 429
        assert fresh.get('/api/sessions/'+first['id'], headers=auth(first['token'])).is_success
        with fresh.app.state.factory() as db:
            assert db.scalar(select(func.count()).select_from(Training)) == 3
    assert not classroom.calls


def test_global_budget_survives_restart_and_allows_replay_and_review(classroom, monkeypatch):
    monkeypatch.setenv('SCAMSENSE_MAX_TURNS', '1')
    rid = str(uuid4())
    with TestClient(create_app(model=classroom)) as client:
        first, second = new(client).json(), new(client).json()
        assert send(client, first, text='').status_code == 422
        assert 'event: done' in send(client, first, rid).text
        assert '全班' in send(client, second).json()['detail']
    monkeypatch.setenv('SCAMSENSE_MAX_TURNS', '0')
    with TestClient(create_app(model=classroom)) as fresh:
        assert send(fresh, second).status_code == 429
        assert '"cached":true' in send(fresh, first, rid).text
        path, headers = '/api/sessions/' + first['id'], auth(first['token'])
        report = fresh.post(path+'/finish', headers=headers, json={'kind':'early'}).json()
        assert report['ending']['kind'] == 'early'
        snap = fresh.get(path, headers=headers).json()
        assert snap['review'] == report and len(snap['messages']) == 2
    assert len(classroom.calls) == 3


def test_failed_attempt_and_retry_each_consume_one_turn(classroom):
    with TestClient(create_app(model=classroom)) as client:
        first, rid = new(client).json(), str(uuid4())
        classroom.break_at = 'analysis'
        assert 'event: error' in send(client, first, rid).text
        classroom.break_at = None
        assert 'event: done' in send(client, first, rid).text
        assert '本场' in send(client, first).json()['detail'] and len(classroom.calls) == 4
        with client.app.state.factory() as db:
            assert db.get(ClassroomSeat, first['id']).attempts == 2


def test_concurrent_sessions_cannot_overbook_the_last_seat_or_turn(classroom, monkeypatch):
    monkeypatch.setenv('SCAMSENSE_MAX_TURNS', '1')
    with TestClient(create_app(model=classroom)) as client, ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: new(client), range(3)))
        assert sorted(r.status_code for r in results) == [201,201,429]
        sessions = [r.json() for r in results if r.is_success]
        turns = list(pool.map(lambda s: send(client, s), sessions))
        assert sorted(r.status_code for r in turns) == [200,429] and len(classroom.calls) == 3


def test_busy_limit_releases_a_slot_without_consuming_a_rejected_attempt(classroom, monkeypatch):
    monkeypatch.setenv('SCAMSENSE_MAX_TURNS', '8')
    monkeypatch.setenv('SCAMSENSE_MAX_SESSIONS', '4')
    with TestClient(create_app(model=classroom)) as client:
        sids = [new(client).json()['id'] for _ in range(4)]
        factory, gate = client.app.state.factory, Classroom.from_env()
        def reserve(sid):
            return training.reserve(factory, sid, str(uuid4()), 'wang', ASK, True, gate)
        holds = [reserve(sid) for sid in sids[:3]]
        with pytest.raises(HTTPException) as error:
            reserve(sids[3])
        assert error.value.status_code == 429
        with factory() as db:
            assert db.get(ClassroomSeat, sids[3]).attempts == 0
        training.fail_turn(factory, sids[0], *holds[0])
        assert reserve(sids[3])


@pytest.mark.parametrize('platform', ['RENDER', 'RAILWAY_PROJECT_ID'])
@pytest.mark.parametrize('problem', ['missing', 'short', 'same_as_provider', 'local_on_host', 'negative_limit'])
def test_hosted_config_fails_closed(classroom, monkeypatch, problem, platform):
    monkeypatch.setenv(platform, 'true' if platform == 'RENDER' else 'test-project')
    monkeypatch.delenv('SCAMSENSE_ACCESS_MODE')
    if problem == 'missing': monkeypatch.delenv('SCAMSENSE_CLASS_INVITE')
    if problem == 'short': monkeypatch.setenv('SCAMSENSE_CLASS_INVITE', 'weak')
    if problem == 'same_as_provider': monkeypatch.setenv('OPENAI_API_KEY', INVITE)
    if problem == 'local_on_host':
        monkeypatch.delenv('SCAMSENSE_CLASS_INVITE')
        monkeypatch.setenv('SCAMSENSE_ACCESS_MODE', 'local')
    if problem == 'negative_limit': monkeypatch.setenv('SCAMSENSE_MAX_TURNS', '-1')
    with pytest.raises(ValueError) as error:
        create_app(model=classroom)
    assert INVITE not in str(error.value)


@pytest.mark.parametrize(('problem', 'message'), [('trial', 'IP 白名单'), ('model', '后端对话模型'), ('port', 'PORT')])
def test_railway_refuses_unsafe_release_before_migrations(monkeypatch, problem, message):
    monkeypatch.setenv('RAILWAY_PROJECT_ID', 'test-project')
    monkeypatch.setenv('SCAMSENSE_CLASS_INVITE', INVITE)
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    if problem == 'trial':
        monkeypatch.setenv('SCAMSENSE_TRIAL_IPS', '')
        monkeypatch.delenv('SCAMSENSE_ACCESS_MODE', raising=False)
    if problem == 'port': monkeypatch.setenv('PORT', '65536')
    monkeypatch.setattr(command, 'upgrade', lambda *_: pytest.fail('Migration ran on a blocked deployment'))
    with pytest.raises(ValueError, match=message):
        serve()


@pytest.mark.parametrize('problem', ['no_mount', 'no_url', 'missing', 'blank', 'outside'])
def test_railway_db_must_already_exist_on_the_named_volume(tmp_path, monkeypatch, problem):
    volume = tmp_path / 'volume'
    volume.mkdir()
    path = (tmp_path if problem == 'outside' else volume) / 'original.sqlite3'
    if problem in {'blank', 'outside'}: path.touch()
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', 'sqlite:///' + path.as_posix())
    monkeypatch.setenv('RAILWAY_PROJECT_ID', 'test-project')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH', str(volume))
    if problem == 'no_mount': monkeypatch.delenv('RAILWAY_VOLUME_MOUNT_PATH')
    if problem == 'no_url': monkeypatch.delenv('SCAMSENSE_DATABASE_URL')
    with pytest.raises(ValueError):
        database_url()
    if problem in {'blank', 'outside'}:
        assert path.stat().st_size == 0
    else:
        assert not path.exists()


def test_railway_serves_existing_database_on_platform_port(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path / 'original.sqlite3').as_posix()
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), '0004_explicit_confirmation')
    with TestClient(create_app(model=ScriptedModel())) as original:
        old = original.post('/api/sessions').json()
        route = '/api/sessions/' + old['id']
        headers = auth(old['token'])
        original.post(route + '/finish', headers=headers, json={'kind':'early'}).raise_for_status()
        snapshot = original.get(route, headers=headers).json()
    monkeypatch.setenv('RAILWAY_PROJECT_ID', 'test-project')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH', str(tmp_path))
    monkeypatch.setenv('SCAMSENSE_CLASS_INVITE', INVITE)
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.setenv('SCAMSENSE_DEEPSEEK_API_KEY', 'test-only-not-a-real-key')
    monkeypatch.setenv('SCAMSENSE_TRIAL_IPS', '192.0.2.1')
    monkeypatch.setenv('SCAMSENSE_ACCESS_MODE', 'classroom')
    monkeypatch.setenv('PORT', '8497')
    def check(app, *, host, port, workers, access_log):
        assert (host, port, workers, access_log) == ('0.0.0.0', 8497, 1, False)
        with TestClient(app) as public:
            assert public.get('/api/health').json()['invite_required'] is True
            assert public.post('/api/sessions').status_code == 403
            assert public.get(route, headers=headers).json() == snapshot
            assert new(public).status_code == 201
    monkeypatch.setattr('uvicorn.run', check)
    serve()


def test_railway_credential_is_isolated_from_legacy_provider_settings(monkeypatch):
    monkeypatch.setenv('RAILWAY_PROJECT_ID', 'test-project')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://example.invalid')
    monkeypatch.setenv('OPENAI_MODEL', 'not-the-classroom-model')
    monkeypatch.setenv('OPENAI_API_KEY', 'legacy-test-key')
    monkeypatch.delenv('SCAMSENSE_DEEPSEEK_API_KEY', raising=False)
    assert not CompatibleModel(classroom=True).configured
    monkeypatch.delenv('OPENAI_API_KEY')
    monkeypatch.setenv('SCAMSENSE_DEEPSEEK_API_KEY', 'test-only-classroom-secret')
    assert not CompatibleModel().configured
    model = CompatibleModel(classroom=True)
    assert model.configured and (model.base, model.name) == ('https://api.deepseek.com', 'deepseek-flash')
    monkeypatch.setenv('SCAMSENSE_DEEPSEEK_API_KEY', INVITE)
    monkeypatch.setenv('SCAMSENSE_CLASS_INVITE', INVITE)
    with pytest.raises(ValueError, match='必须分开'):
        Classroom.from_env()


def test_hosted_deepseek_contract_without_network(monkeypatch):
    monkeypatch.delenv('OPENAI_BASE_URL', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-provider-credential')
    monkeypatch.setattr('backend.model.getproxies', lambda: {})
    async def offline_post(self, url, *, headers, json):
        assert url == 'https://api.deepseek.com/chat/completions' and headers == auth('test-only-provider-credential')
        assert json['model'] == 'deepseek-flash' and json['thinking'] == {'type':'disabled'}
        assert json['response_format'] == {'type':'json_object'} and json['max_tokens'] == 2048
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices':[{'message':{'content':'{"actions":[]}'}}]})
    monkeypatch.setattr(httpx.AsyncClient, 'post', offline_post)
    result = asyncio.run(CompatibleModel(classroom=True).analyze('wang', [], '你好。'))
    assert result.actions == []
