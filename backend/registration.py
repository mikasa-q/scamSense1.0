from typing import Literal

from sqlalchemy import select

from .db import Message, RegistrationConfirmation, RegistrationEntry, StoryEvent, Trace

FieldKey = Literal['project_experience', 'city']
Status = Literal['agreed', 'submitted', 'deferred', 'refused']
CHAT_STATUSES = {'agreed', 'deferred', 'refused'}
OptionId = Literal['project_a', 'city_b']
Availability = Literal['not_invited', 'open', 'stopped', 'scope_pending']
LEGACY_ITEMS = {'legacy_city_refusal': ('city', 'refused'), 'legacy_project_refusal': ('project_experience', 'refused'),
                'legacy_city_deferred': ('city', 'deferred'), 'legacy_project_deferred': ('project_experience', 'deferred')}
LEGACY_TRACE_KIND = {'items_only': 'legacy_item_decline', 'whole': 'decline',
                     'city_only': 'legacy_city_refusal', 'project_only': 'legacy_project_refusal',
                     'city_later': 'legacy_city_deferred', 'project_later': 'legacy_project_deferred'}
FIELDS = {
    'project_experience': {'option_id': 'project_a', 'label': '项目经历', 'placeholder': '虚构项目 A'},
    'city': {'option_id': 'city_b', 'label': '所在城市', 'placeholder': '虚构城市 B'},
}
OPTIONS = {spec['option_id']: key for key, spec in FIELDS.items()}


def was_invited(db, sid):
    return db.scalar(select(StoryEvent.id).join(Message, Message.id == StoryEvent.message_id).where(
        StoryEvent.sid == sid, StoryEvent.kind == 'registration_proposed',
        Message.sid == sid, Message.role == 'chen', Message.speaker == 'assistant',
    ).limit(1)) is not None


def availability(invited, stopped, pending) -> Availability:
    if stopped:
        return 'stopped'
    if pending:
        return 'scope_pending'
    return 'open' if invited else 'not_invited'


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
    rows = db.execute(select(RegistrationEntry, Message.body).join(Message, Message.id == RegistrationEntry.reply_id)
                      .where(RegistrationEntry.sid == sid))
    ordered = [((e.message_id, 0, e.position, e.id),
                dict(source='chat', field=e.field, status=e.status, quote=e.quote, position=e.position,
                     message_id=e.message_id, reply_id=e.reply_id, reply_quote=body)) for e, body in rows]
    for c in db.scalars(select(RegistrationConfirmation).where(RegistrationConfirmation.sid == sid)):
        ordered.append(((c.after_message_id, 1, 0, c.id),
                        dict(source='explicit', field=c.field, status='submitted', value=c.value, created=c.created)))
    return [entry for _, entry in sorted(ordered, key=lambda pair: pair[0])]


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
        if e['source'] == 'chat':
            items[key].update(status=e['status'], quote=e['quote'], message_id=e['message_id'])
        # A later change of mind cannot undo an earlier transmission.
        if e['status'] == 'submitted':
            submitted.add(key)
    old = select(Trace).where(Trace.sid == sid, Trace.kind.in_(LEGACY_ITEMS))
    for t in db.scalars(old):
        apply_legacy_refusal(items.values(), t.kind, t.quote, t.message_id)
    return dict(items=list(items.values()), submitted=[k for k in items if k in submitted])
