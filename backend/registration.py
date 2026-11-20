from typing import Literal

from sqlalchemy import select

from .db import Message, RegistrationEntry, StoryEvent

FieldKey = Literal['project_experience', 'city']
Status = Literal['agreed', 'submitted', 'deferred', 'refused']
FIELDS = {
    'project_experience': {'label': '项目经历', 'placeholder': '虚构项目 A'},
    'city': {'label': '所在城市', 'placeholder': '虚构城市 B'},
}


def was_invited(db, sid):
    return db.scalar(select(StoryEvent.id).where(
        StoryEvent.sid == sid, StoryEvent.kind == 'registration_proposed'
    ).limit(1)) is not None


def registration_log(db, sid):
    rows = db.execute(select(RegistrationEntry, Message.body)
                      .join(Message, Message.id == RegistrationEntry.reply_id)
                      .where(RegistrationEntry.sid == sid).order_by(RegistrationEntry.id))
    return [dict(field=e.field, status=e.status, quote=e.quote, message_id=e.message_id,
                 reply_id=e.reply_id, reply_quote=body) for e, body in rows]


def registration_state(entries):
    items = {key: dict(key=key, **spec, status=None, quote=None, message_id=None)
             for key, spec in FIELDS.items()}
    submitted = set()
    for e in entries:
        key = e['field']
        items[key].update(status=e['status'], quote=e['quote'], message_id=e['message_id'])
        # A later change of mind cannot undo an earlier transmission.
        if e['status'] == 'submitted':
            submitted.add(key)
    return dict(items=list(items.values()), submitted=[k for k in items if k in submitted])
