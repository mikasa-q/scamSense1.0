from contextlib import contextmanager
import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROOT = Path(__file__).resolve().parents[1]

def database_url():
    if url := os.getenv('SCAMSENSE_DATABASE_URL'):
        return url
    folder = ROOT / 'data'
    folder.mkdir(exist_ok=True)
    return f'sqlite:///{(folder / "scamsense.sqlite3").as_posix()}'

def engine_for(url):
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 10})
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
