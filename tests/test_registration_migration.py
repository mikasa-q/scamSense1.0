from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from backend import training
from backend.db import ROOT, Message, Receipt, Review, StoryEvent, Trace, engine_for


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
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0002_partial_registration'
        assert conn.execute(text('PRAGMA foreign_key_check')).all() == []
    training.check_access(factory, sid, session['token'])
    snap = training.snapshot(factory, sid)
    assert [(m['id'],m['body']) for m in snap['messages']] == [(invite.id,invite.body),(stop.id,stop.body)]
    assert snap['registered'] and snap['registration']['declined_all']
    assert snap['registration']['history'] == snap['registration']['submitted'] == []
    assert training.snapshot(factory, previous)['review'] == {'original':'保留旧复盘'}
    engine.dispose()
