from typing import Literal

from sqlalchemy import select

from .db import Message, RegistrationEntry, StoryEvent, Trace

FieldKey = Literal['project_experience', 'city']
Status = Literal['agreed', 'submitted', 'deferred', 'refused']
LEGACY_ITEMS = {'legacy_city_refusal': ('city', 'refused'), 'legacy_project_refusal': ('project_experience', 'refused'),
                'legacy_city_deferred': ('city', 'deferred'), 'legacy_project_deferred': ('project_experience', 'deferred')}
LEGACY_TRACE_KIND = {'items_only': 'legacy_item_decline', 'whole': 'decline',
                     'city_only': 'legacy_city_refusal', 'project_only': 'legacy_project_refusal',
                     'city_later': 'legacy_city_deferred', 'project_later': 'legacy_project_deferred'}
FIELDS = {
    'project_experience': {'label': '项目经历', 'placeholder': '虚构项目 A'},
    'city': {'label': '所在城市', 'placeholder': '虚构城市 B'},
}


def was_invited(db, sid):
    return db.scalar(select(StoryEvent.id).where(
        StoryEvent.sid == sid, StoryEvent.kind == 'registration_proposed'
    ).limit(1)) is not None


def registration_controls(db, sid):
    pending = []
    controls = (select(Trace, Message.body).join(Message, Message.id == Trace.message_id)
                .where(Trace.sid == sid, Message.sid == sid, Message.role == 'chen', Message.speaker == 'user',
                       Trace.kind.in_(['decline', 'resume_registration', 'legacy_decline']))
                .order_by(Trace.message_id.desc(), Trace.id.desc()))
    for trace, body in db.execute(controls):
        if trace.kind == 'decline':
            return True, []  # A later refusal of unknown scope cannot reopen a confirmed stop.
        if trace.kind == 'resume_registration':
            break
        pending.append(dict(id=trace.id, message_id=trace.message_id, quote=trace.quote, message=body))
    return False, pending[::-1]


def registration_log(db, sid):
    rows = db.execute(select(RegistrationEntry, Message.body)
                      .join(Message, Message.id == RegistrationEntry.reply_id)
                      .where(RegistrationEntry.sid == sid)
                      .order_by(RegistrationEntry.message_id, RegistrationEntry.position, RegistrationEntry.id))
    return [dict(field=e.field, status=e.status, quote=e.quote, position=e.position, message_id=e.message_id,
                 reply_id=e.reply_id, reply_quote=body) for e, body in rows]


def registration_snapshot(db, sid):
    history = registration_log(db, sid)
    stopped, pending = registration_controls(db, sid)
    return dict(**registration_state(db, sid, history), history=history, declined_all=stopped, scope_pending=bool(pending))


def apply_legacy_refusal(items, kind, quote, message_id):
    if kind in LEGACY_ITEMS:
        field, status = LEGACY_ITEMS[kind]
        for item in items:
            if item['key'] == field and message_id > (item['message_id'] or 0):
                item.update(status=status, quote=quote, message_id=message_id)


def registration_state(db, sid, entries):
    items = {key: dict(key=key, **spec, status=None, quote=None, message_id=None)
             for key, spec in FIELDS.items()}
    submitted = set()
    for e in entries:
        key = e['field']
        items[key].update(status=e['status'], quote=e['quote'], message_id=e['message_id'])
        # A later change of mind cannot undo an earlier transmission.
        if e['status'] == 'submitted':
            submitted.add(key)
    old = select(Trace).where(Trace.sid == sid, Trace.kind.in_(LEGACY_ITEMS))
    for t in db.scalars(old):
        apply_legacy_refusal(items.values(), t.kind, t.quote, t.message_id)
    return dict(items=list(items.values()), submitted=[k for k in items if k in submitted])
