from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROOT = Path(__file__).resolve().parents[1]

def database_url():
    url = os.getenv('SCAMSENSE_DATABASE_URL')
    if os.getenv('RAILWAY_PROJECT_ID'):
        mount = Path(os.getenv('RAILWAY_VOLUME_MOUNT_PATH') or '.')
        if not url or not mount.is_absolute() or not mount.is_dir():
            raise ValueError('Railway 更新须指定原持久卷及其现有 SQLite 连接串。')
        parsed = make_url(url)
        path = Path(parsed.database or '.')
        if (parsed.drivername != 'sqlite' or parsed.host or parsed.query or not path.is_absolute()
                or not path.resolve().is_relative_to(mount.resolve()) or not path.is_file()):
            raise ValueError('拒绝迁移：数据库必须是原持久卷上已存在的 SQLite 文件。')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('trainings','alembic_version')").fetchall()
        if len(tables) != 2:
            raise ValueError('拒绝迁移：指定的文件不是已有的 ScamSense 数据库。')
    if url:
        return url
    folder = ROOT / 'data'
    folder.mkdir(exist_ok=True)
    return f'sqlite:///{(folder / "scamsense.sqlite3").as_posix()}'

def engine_for(url):
    engine = create_engine(url, hide_parameters=True, connect_args={'check_same_thread': False, 'timeout': 10})
    @event.listens_for(engine, 'connect')
    def sqlite_constraints(conn, _record):
        conn.execute('PRAGMA foreign_keys=ON')
    return engine

@contextmanager
def writer(factory):
    with factory() as db, db.begin():
        db.execute(text('BEGIN IMMEDIATE'))
        yield db

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def uid():
    return uuid4().hex

class Base(DeclarativeBase):
    pass

class Training(Base):
    __tablename__ = 'trainings'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64))
    created: Mapped[str] = mapped_column(String, default=now)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[bool] = mapped_column(default=False)
    locked_by: Mapped[str | None] = mapped_column(String(32))
    lock_until: Mapped[int] = mapped_column(Integer, default=0)

class ClassroomSeat(Base):
    __tablename__ = 'classroom_seats'
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)

class Receipt(Base):
    __tablename__ = 'receipts'
    __table_args__ = (UniqueConstraint('sid', 'request_id'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12))

class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), index=True)
    receipt: Mapped[str] = mapped_column(ForeignKey('receipts.id'))
    role: Mapped[str] = mapped_column(String(12))
    speaker: Mapped[str] = mapped_column(String(12))
    body: Mapped[str] = mapped_column(Text)
    created: Mapped[str] = mapped_column(String, default=now)

class StoryEvent(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(primary_key=True)
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    stage: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(ForeignKey('messages.id'))

class Trace(Base):
    __tablename__ = 'traces'
    id: Mapped[int] = mapped_column(primary_key=True)
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey('messages.id'))
    kind: Mapped[str] = mapped_column(String(32))
    focus: Mapped[str] = mapped_column(String(12))
    quote: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text)

def evidence_rows(sid):
    # Pre-K04 topic excerpts are historical traces, not audited disclosures.
    legacy_excerpt = (Trace.focus == 'K04') & (Trace.kind == 'disclosure')
    return (select(Trace, Message).join(Message, Trace.message_id == Message.id)
            .where(Trace.sid == sid, Message.sid == sid, ~legacy_excerpt))

class RegistrationEntry(Base):
    __tablename__ = 'registration_entries'
    __table_args__ = (UniqueConstraint('message_id', 'field', 'position', name='uq_registration_field_position'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey('messages.id'))
    reply_id: Mapped[int] = mapped_column(ForeignKey('messages.id'))
    position: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(12))
    quote: Mapped[str] = mapped_column(Text)

class RegistrationConfirmation(Base):
    __tablename__ = 'registration_confirmations'
    __table_args__ = (UniqueConstraint('sid', 'field', name='uq_confirmation_field'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'))
    field: Mapped[str] = mapped_column(String(24))
    value: Mapped[str] = mapped_column(String(24))
    created: Mapped[str] = mapped_column(String, default=now)
    # Orders clicks between real chat turns; this is not a message authored by the user.
    after_message_id: Mapped[int] = mapped_column(ForeignKey('messages.id'))

class Ending(Base):
    __tablename__ = 'endings'
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))
    choice: Mapped[str | None] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    cited: Mapped[list] = mapped_column(JSON)
    created: Mapped[str] = mapped_column(String, default=now)

class Review(Base):
    __tablename__ = 'reviews'
    sid: Mapped[str] = mapped_column(ForeignKey('trainings.id'), primary_key=True)
    rubric: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
