from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend import training
from backend.db import ROOT, Message, Receipt, Trace, engine_for
from backend.policy import Action, permission


def test_upgrade_scopes_legacy_refusals_without_reordering_newer_choices(tmp_path, monkeypatch):
    url = f'sqlite:///{(tmp_path / "legacy.db").as_posix()}'
    monkeypatch.setenv('SCAMSENSE_DATABASE_URL', url)
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, '0001_training')
    engine = engine_for(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    partial, whole = (training.create(factory)['id'] for _ in range(2))

    def old_turn(sid, body, *, decline=False):
        with factory.begin() as db:
            receipt = Receipt(sid=sid, request_id=str(uuid4()), fingerprint='old', attempt='old', status='done')
            db.add(receipt)
            db.flush()
            user, reply = [Message(sid=sid, receipt=receipt.id, role='chen', speaker=s, body=b)
                           for s, b in [('user', body), ('assistant', '明白。')]]
            db.add_all([user, reply])
            db.flush()
            if decline:
                db.add(Trace(sid=sid, message_id=user.id, kind='decline', focus='none', quote=body, why='保留拒绝意愿，不再主动提出登记。'))
            return user.id, reply.id

    refusal = '我只拒绝提供所在城市'
    user, reply = old_turn(partial, refusal, decline=True)
    old_turn(whole, '我不参与预登记。', decline=True)
    command.upgrade(config, '0002_registration_entries')
    project = '项目经历：虚构项目 A'
    later, ack = old_turn(partial, project)
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO registration_entries (sid,message_id,reply_id,field,status,quote) '
                          "VALUES (:sid,:mid,:rid,'project_experience','submitted',:quote)"),
                     dict(sid=partial, mid=later, rid=ack, quote=project))
    command.upgrade(config, 'head')

    interest = Action(kind='interest', opportunity='chen', focus='none', quote='想了解该岗位', source='own')
    for sid, allow in [(partial, True), (whole, False)]:
        ctx = training.private_context(factory, sid, 'chen')[2]
        assert permission('chen', [interest], set(), ctx)[1] is allow
    snap = training.snapshot(factory, partial)['registration']
    assert [i['status'] for i in snap['items']] == ['submitted', 'refused']
    review = training.finish(factory, partial, 'early', None, '', [])['registration']
    assert review['submitted'] == ['project_experience'] and review['items'] == snap['items']
    assert [(e['message_id'], e['reply_id'], e['quote']) for e in review['history']] == [
        (user, reply, refusal), (later, ack, project)]
    assert review['declined_all'] is False
    assert training.finish(factory, whole, 'early', None, '', [])['registration']['declined_all'] is True
    engine.dispose()
