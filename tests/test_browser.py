"""Opt-in tests of frontend/dist against a real loopback API and a test-only model."""
import asyncio
import os
import socket
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from backend.db import ROOT, Message, Receipt, StoryEvent, Trace
from backend.main import create_app
from backend.model import WANG_GENERATE, K05_AUDIT, K05_INTERPRET, CompatibleModel
from test_model_wire import (AUTH_REPLY, CHEN_ASK, CHEN_GAP, CHEN_STARTER, INTEREST, LIN_ASK,
                             LIN_ROUTE, LIN_STARTER, MIXED, QUESTION, REPLY, RESUME, SOURCE_REPLY,
                             STOP, WANG_STARTER, wire_fixture)

pytestmark = pytest.mark.skipif(os.getenv('SCAMSENSE_TEST_BROWSER') != '1', reason='enable built-page browser tests explicitly')


@contextmanager
def running_api(app):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); sock.listen()
        url = f'http://127.0.0.1:{sock.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True)
        thread.start()
        try:
            with httpx.Client(trust_env=False, timeout=10) as client:
                assert client.get(url + '/api/health').json()['model_configured']
            yield url
        finally:
            server.should_exit = True
            thread.join(15)
            assert not thread.is_alive()


@pytest.fixture
def ui(tmp_path, monkeypatch, request):
    from playwright.sync_api import sync_playwright
    assert (ROOT / 'frontend/dist/index.html').is_file(), 'Build the frontend before running browser tests.'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', f'sqlite:///{(tmp_path / "ui.db").as_posix()}')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('OPENAI_MODEL', 'wire-test-only')
    invite = getattr(request, 'param', None)
    if invite:
        monkeypatch.setenv('SCAMSENSE_ACCESS_MODE', 'classroom')
        monkeypatch.setenv('SCAMSENSE_CLASS_INVITE', invite)
        monkeypatch.setenv('SCAMSENSE_MAX_TURNS', '1')
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    with wire_fixture() as (base, calls), sync_playwright() as pw:
        monkeypatch.setenv('OPENAI_BASE_URL', base)
        app = create_app()
        with running_api(app) as url:
            browser = pw.chromium.launch(channel=os.getenv('SCAMSENSE_BROWSER_CHANNEL') or None)
            page = browser.new_context().new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(type(e).__name__))
            page.goto(url)
            if not invite:
                page.get_by_role('button', name='进入训练').click()
                page.locator('#message').wait_for()
            try:
                yield SimpleNamespace(page=page, url=url, calls=calls, factory=app.state.factory, invite=invite)
            finally:
                browser.close()
            assert not errors


def send(page, text):
    page.locator('#message').fill(text)
    page.get_by_role('button', name='发送', exact=True).click()
    page.locator('.message.user:not(.draft-bubble) p').filter(has_text=text).wait_for()


def archive_new(page):
    page.get_by_role('link', name='训练记录', exact=True).click()
    page.get_by_role('button', name='新建训练').click()
    page.locator('#message').wait_for()


def counts(ui, sid):
    with ui.factory() as db:
        return tuple(db.scalar(select(func.count()).select_from(t).where(t.sid == sid)) for t in (Receipt, StoryEvent, Trace))


@pytest.mark.parametrize('ui', ['classroom-only-test-invitation-with+slash/and=padding'], indirect=True)
def test_shared_invite_creates_private_training_and_removes_fragment(ui):
    from playwright.sync_api import expect
    p = ui.page
    start = p.get_by_role('button', name='进入训练')
    start.click()
    expect(p.get_by_role('alert')).to_contain_text('有效邀请')
    requests = []
    p.on('request', lambda req: requests.append(req.url))
    p.goto(ui.url + '/#invite=' + ui.invite)
    expect(p.get_by_role('status')).to_contain_text('已读取邀请')
    assert p.url == ui.url + '/#/desk'
    p.reload()
    expect(p.get_by_role('status')).to_contain_text('已读取邀请')
    start.click()
    send(p, QUESTION)
    expect(p.locator('.message.assistant p')).to_have_text(REPLY)
    first_url = p.url
    assert ui.invite not in p.evaluate('JSON.stringify(localStorage)')
    assert not any(ui.invite in url for url in requests)
    assert len(ui.calls) == 3

    other = p.context.browser.new_context()
    try:
        peer = other.new_page()
        peer.goto(first_url)
        expect(peer.get_by_role('alert')).to_contain_text('没有这场训练的访问凭据')
        peer.goto(ui.url + '/#invite=' + ui.invite)
        peer.get_by_role('button', name='进入训练').click()
        peer.locator('#message').fill(QUESTION)
        assert peer.url != first_url
        peer.get_by_role('button', name='发送', exact=True).click()
        expect(peer.get_by_role('alert')).to_contain_text('全班的对话额度已用完')
        assert len(ui.calls) == 3
    finally:
        other.close()
    p.reload()
    expect(p.locator('.message.assistant p')).to_have_text(REPLY)
    p.get_by_role('button', name='提前结束训练').click()
    p.get_by_role('button', name='结束并查看复盘').click()
    expect(p.get_by_text('你结束了模拟，没有作正式招聘决定。')).to_be_visible()


def test_prompt_chips_and_identical_typed_questions_use_the_same_turn(ui):
    from playwright.sync_api import expect
    p = ui.page
    contacts = [('wang', '王宇 大学同学', WANG_STARTER, SOURCE_REPLY),
                ('chen', '陈浩 招聘顾问', CHEN_STARTER, AUTH_REPLY),
                ('lin', '林悦 企业 HR', LIN_STARTER, LIN_ROUTE)]
    clicked = {}
    for use_chip in (True, False):
        if not use_chip:
            archive_new(p)
        for role, name, text, reply in contacts:
            p.get_by_role('link', name=name).click()
            before = len(ui.calls)
            if use_chip:
                p.get_by_role('button', name='试着问：' + text).click()
            else:
                p.locator('#message').fill(text)
            expect(p.locator('#message')).to_have_value(text)
            with p.expect_request('**/turns') as req:
                p.get_by_role('button', name='发送', exact=True).click()
            wire = req.value.post_data_json
            assert set(wire) == {'role', 'text', 'request_id'} and (wire['role'], wire['text']) == (role, text)
            expect(p.locator('.message.user:not(.draft-bubble) p')).to_have_text([text])
            expect(p.locator('.message.assistant p')).to_have_text([reply])
            expect(p.get_by_role('alert')).to_have_count(0)
            calls = ui.calls[before:]
            assert len(calls) == 3 and all(data['private_history'] == [] for _, data in calls)
            if use_chip:
                clicked[role] = calls
            else:
                assert clicked[role] == calls


def test_three_contacts_confirmation_decision_and_early_end(ui):
    from playwright.sync_api import expect
    p = ui.page
    send(p, QUESTION)
    p.get_by_role('link', name='林悦 企业 HR').click(); send(p, LIN_ASK)
    p.get_by_role('link', name='陈浩 招聘顾问').click(); send(p, CHEN_ASK); send(p, INTEREST); send(p, MIXED)
    panel = p.get_by_role('region', name='候选人预登记')
    project = panel.get_by_role('button', name='提交虚构项目 A')
    expect(panel).to_contain_text('已提交项：无')
    stale = p.context.new_page()
    stale.goto(p.url); stale.get_by_role('button', name='提交虚构城市 B').wait_for()
    send(p, STOP)
    stale.get_by_role('button', name='提交虚构城市 B').click()
    expect(stale.get_by_role('alert')).to_contain_text('停止')
    expect(stale.get_by_role('button', name='提交虚构城市 B')).to_have_count(0)
    stale.close()
    send(p, RESUME)
    expect(panel).to_contain_text('已提交项：无')
    # Lose the response after the button POST really committed.
    def lose_response(route):
        assert route.fetch().ok
        route.abort('failed')
    p.route('**/registration/confirm', lose_response, times=1)
    project.click()
    expect(project).to_be_disabled()
    expect(panel).to_contain_text('显式确认 · 虚构项目 A')
    expect(panel.get_by_role('button', name='提交虚构城市 B')).to_be_enabled()
    p.reload(); expect(project).to_be_disabled()
    p.get_by_role('button', name='作出决策').click()
    p.get_by_role('radio', name='仅提交必要资料', exact=False).check()
    p.locator('#reason').fill('缺少可独立核对这条转发的依据。')
    p.get_by_text('引用本场原话', exact=False).click()
    p.get_by_role('checkbox', name=CHEN_GAP, exact=False).check()
    p.get_by_role('button', name='提交并查看复盘').click()
    expect(p.get_by_role('heading', name='仅提交必要资料')).to_be_visible()
    p.reload(); expect(p.get_by_role('heading', name='已提交项：项目经历')).to_be_visible()
    refs = p.locator('article.ref-entry')
    for reply in (LIN_ROUTE, CHEN_GAP, REPLY):
        expect(refs.filter(has_text=reply).last).to_be_visible()
    refs.filter(has_text=LIN_ROUTE).last.get_by_role('link', name='定位原话').click()
    expect(p.locator('.message.highlight p')).to_have_text(LIN_ROUTE)
    expect(p.locator('.thread-head')).to_contain_text('林悦')
    assert '/lin?m=' in p.url
    archive_new(p)
    p.get_by_role('button', name='提前结束训练').click(); p.get_by_role('button', name='结束并查看复盘').click()
    expect(p.get_by_text('你结束了模拟，没有作正式招聘决定。')).to_be_visible()
    expect(p.get_by_text('证据不足', exact=True)).to_have_count(4)


def test_refresh_during_sse_and_replay_completed_request(ui, monkeypatch):
    from playwright.sync_api import expect
    p, gate, entered = ui.page, threading.Event(), threading.Event()
    reply = CompatibleModel.reply
    async def hold(self, *args):
        entered.set()
        assert await asyncio.to_thread(gate.wait, 15)
        return await reply(self, *args)
    monkeypatch.setattr(CompatibleModel, 'reply', hold)
    p.locator('#message').fill(QUESTION)
    with p.expect_request('**/turns') as sent:
        p.get_by_role('button', name='发送', exact=True).click()
    try:
        assert entered.wait(8)
        # Browser history/hash navigation is possible even while the roster is locked.
        p.evaluate("location.hash = location.hash.replace('/wang', '/lin')")
        expect(p.locator('.thread-head')).to_contain_text('林悦')
        expect(p.locator('.draft-bubble')).to_have_count(0)
        p.go_back()
        p.reload(); expect(p.locator('#message')).to_be_disabled()
    finally:
        gate.set()
    expect(p.locator('.message.assistant p')).to_have_text(REPLY, timeout=12000)
    expect(p.locator('#message')).to_have_value('')
    req = sent.value
    sid = req.url.split('/sessions/')[1].split('/')[0]
    before = counts(ui, sid)
    replay = p.request.post(req.url, headers={'Authorization':req.header_value('authorization')}, data=req.post_data_json)
    assert replay.ok and '"cached":true' in replay.text()
    assert counts(ui, sid) == before == (1, 2, 2) and len(ui.calls) == 3
    p.reload(); expect(p.locator('.message')).to_have_count(2)


def test_refresh_during_sse_recovers_over_slow_session_reads(ui, monkeypatch):
    from playwright.sync_api import expect
    p, gate, entered = ui.page, threading.Event(), threading.Event()
    sid = p.url.split('/chat/')[1].split('/')[0]
    detail = f'{ui.url}/api/sessions/{sid}'
    draft_key = f'scamsense.pending.{sid}.wang'
    turn_ids = []
    def record_turn(req):
        if req.method == 'POST' and req.url == detail + '/turns':
            turn_ids.append(req.post_data_json['request_id'])
    p.on('request', record_turn)

    reply = CompatibleModel.reply
    async def hold(self, *args):
        entered.set()
        assert await asyncio.to_thread(gate.wait, 30)
        return await reply(self, *args)
    monkeypatch.setattr(CompatibleModel, 'reply', hold)
    composer = p.locator('#message')
    try:
        composer.fill(QUESTION)
        p.get_by_role('button', name='发送', exact=True).click()
        assert entered.wait(8)
        p.reload()
        expect(p.locator('.working')).to_contain_text('上一次发言仍在处理')
        expect(composer).to_be_disabled()
        expect(composer).to_have_value(QUESTION)
        assert turn_ids == [p.evaluate('k => JSON.parse(sessionStorage.getItem(k)).id', draft_key)]

        # Throttle real responses without serializing concurrent requests in a route handler.
        cdp = p.context.new_cdp_session(p)
        cdp.send('Network.enable')
        cdp.send('Network.emulateNetworkConditions', {
            'offline': False, 'latency': 3200, 'downloadThroughput': -1, 'uploadThroughput': -1,
        })
        p.evaluate('performance.clearResourceTimings()')
        busy = p.wait_for_event('response', predicate=lambda r: r.url == detail, timeout=15000)
        assert busy.ok and busy.json()['busy']
    finally:
        gate.set()

    expect(p.locator('.message.assistant p')).to_have_text([REPLY], timeout=16000)
    expect(p.locator('.message.user p')).to_have_text([QUESTION])
    expect(composer).to_be_enabled()
    expect(composer).to_have_value('')
    assert p.evaluate('k => sessionStorage.getItem(k) === null', draft_key)
    reads = p.evaluate('url => performance.getEntriesByName(url).map(r => [r.startTime, r.responseEnd])', detail)
    assert len(reads) >= 2 and all(end - start > 2500 for start, end in reads)
    assert all(prev[1] <= nxt[0] for prev, nxt in zip(reads, reads[1:]))
    assert len(turn_ids) == 1
    with ui.factory() as db:
        assert db.execute(select(Receipt.request_id, Receipt.status).where(Receipt.sid == sid)).one() == (turn_ids[0], 'done')
        assert db.scalars(select(Message.speaker).where(Message.sid == sid).order_by(Message.id)).all() == ['user', 'assistant']
    assert counts(ui, sid) == (1, 2, 2)
    assert [prompt for prompt, _ in ui.calls] == [K05_INTERPRET, WANG_GENERATE, K05_AUDIT]


def test_missing_terminal_sse_frame_recovers_committed_reply(ui):
    from playwright.sync_api import expect
    p = ui.page
    def drop_done(route):
        response = route.fetch()
        assert response.ok and 'event: done' in response.text()
        route.fulfill(content_type='text/event-stream', body=': interrupted before done\n\n')
    p.route('**/turns', drop_done, times=1)
    send(p, QUESTION)
    expect(p.locator('.message.assistant p')).to_have_text(REPLY)
    expect(p.locator('#message')).to_have_value('')
    expect(p.get_by_role('alert')).to_have_count(0)
    p.reload(); expect(p.locator('.message')).to_have_count(2)
    assert counts(ui, p.url.split('/chat/')[1].split('/')[0]) == (1, 2, 2) and len(ui.calls) == 3
    # Citing a message without a reason still preserves the link, not a judgment.
    p.get_by_role('button', name='作出决策').click(); p.get_by_role('radio', name='先核实再决定', exact=False).check()
    p.get_by_text('引用本场原话', exact=False).click(); p.get_by_role('checkbox', name=REPLY, exact=False).check()
    p.get_by_role('button', name='提交并查看复盘').click()
    expect(p.get_by_role('heading', name='先核实再决定')).to_be_visible()
    expect(p.locator('.dimension').filter(has_text='决策合理性')).to_contain_text('证据不足')
    p.locator('.report-summary').get_by_role('link', name='定位原话').click(timeout=3000)
    expect(p.locator('.message.highlight p')).to_have_text(REPLY)


def test_refresh_after_failed_turn_retries_same_receipt(ui, monkeypatch):
    from playwright.sync_api import expect
    p = ui.page
    original = CompatibleModel.reply
    async def timeout(*args):
        raise TimeoutError()
    monkeypatch.setattr(CompatibleModel, 'reply', timeout)
    p.locator('#message').fill(QUESTION)
    with p.expect_request('**/turns') as failed:
        p.get_by_role('button', name='发送', exact=True).click()
    expect(p.get_by_role('alert')).to_contain_text('可原样重试')
    expect(p.locator('.message')).to_have_count(0)
    p.reload(); expect(p.locator('#message')).to_have_value(QUESTION)
    expect(p.get_by_role('alert')).to_contain_text('重试')
    monkeypatch.setattr(CompatibleModel, 'reply', original)
    with p.expect_request('**/turns') as retry:
        p.get_by_role('button', name='发送', exact=True).click()
    expect(p.locator('.message.assistant p')).to_have_text(REPLY)
    assert retry.value.post_data_json['request_id'] == failed.value.post_data_json['request_id']
    sid = retry.value.url.split('/sessions/')[1].split('/')[0]
    assert counts(ui, sid) == (1, 2, 2)
