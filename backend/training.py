import hashlib
import secrets
import time
from fastapi import HTTPException
from sqlalchemy import select
from .db import Ending, Message, Receipt, RegistrationEntry, Review, StoryEvent, Trace, Training, uid, writer
from .policy import ASKS, REGISTRATION_ACTIONS, WHY, InvalidSubmissionValue, check_generated, permission, registration_turn, validate_actions, validate_reply
from .registration import LEGACY_TRACE_KIND, apply_legacy_refusal, registration_controls, registration_log, registration_snapshot, registration_state, was_invited
from .review import RUBRIC, make_review, message_dict


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def create(factory):
    token = secrets.token_urlsafe(32)
    with writer(factory) as db:
        s = Training(token_hash=digest(token))
        db.add(s)
        db.flush()
        db.add(StoryEvent(sid=s.id, kind='created', stage=0))
        return dict(id=s.id, token=token, created=s.created)

def check_access(factory, sid, token):
    with factory() as db:
        s = db.get(Training, sid)
        if not s or not secrets.compare_digest(s.token_hash, digest(token)):
            raise HTTPException(404, '本场训练不存在，或当前浏览器没有访问凭据。')

def is_busy(s):
    return bool(s.locked_by and s.lock_until > time.time())

def snapshot(factory, sid):
    with factory() as db:
        s = db.get(Training, sid)
        messages = db.scalars(select(Message).where(Message.sid == sid).order_by(Message.id)).all()
        review = db.get(Review, sid)
        return dict(id=s.id, created=s.created, stage=s.stage, closed=s.closed, busy=is_busy(s),
                    registered=was_invited(db, sid), registration=registration_snapshot(db, sid),
                    messages=[message_dict(m) for m in messages], review=review.payload if review else None)

def reserve(factory, sid, request_id, role, text, configured):
    fingerprint = digest(role + '\0' + text)
    with writer(factory) as db:
        s = db.get(Training, sid)
        r = db.scalar(select(Receipt).where(Receipt.sid == sid, Receipt.request_id == request_id))
        if r and r.fingerprint != fingerprint:
            raise HTTPException(409, '该请求编号已用于不同的发言。')
        if r and r.status == 'done':
            return None
        if s.closed:
            raise HTTPException(409, '训练已结束，可在复盘中回看原话。')
        if is_busy(s):
            raise HTTPException(409, '本场有发言正在处理，请稍后刷新查看。')
        if not configured:
            raise HTTPException(503, '尚未连接对话模型。请在后端配置模型后重试；本轮未写入。')
        attempt = uid()
        s.locked_by, s.lock_until = attempt, int(time.time()) + 200
        if r:
            r.attempt, r.status = attempt, 'working'
        else:
            r = Receipt(sid=sid, request_id=request_id, fingerprint=fingerprint, attempt=attempt, status='working')
            db.add(r)
        db.flush()
        return r.id, attempt

def private_context(factory, sid, role):
    with factory() as db:
        msgs = db.scalars(select(Message).where(Message.sid == sid, Message.role == role).order_by(Message.id.desc()).limit(24)).all()
        history = [{'speaker':m.speaker, 'text':m.body} for m in reversed(msgs)]
        previous = set(db.scalars(select(Trace.focus).join(Message, Message.id == Trace.message_id).where(Trace.sid == sid, Trace.kind == 'disclosure', Message.role == role)))
        registration = None
        if role == 'chen':
            registration = registration_state(db, sid, registration_log(db, sid))
            registration['invited'] = was_invited(db, sid)
            registration['declined_all'], pending = registration_controls(db, sid)
            if pending:
                registration['legacy_declines'] = pending
        return history, previous, registration

def record_event(db, s, kind, stage, mid=None):
    s.stage = max(s.stage, stage)
    db.add(StoryEvent(sid=s.id, kind=kind, stage=s.stage, message_id=mid))

def store_turn(factory, sid, rid, attempt, role, text, body, actions, disclosed, reg, registered, legacy_scopes):
    with writer(factory) as db:
        s, receipt = db.get(Training, sid), db.get(Receipt, rid)
        if s.closed or s.locked_by != attempt or receipt.attempt != attempt or not is_busy(s):
            raise ValueError('stale attempt')
        for trace_id, scope in legacy_scopes.items():
            if scope != 'uncertain':
                trace = db.get(Trace, trace_id)
                trace.kind = LEGACY_TRACE_KIND[scope]
        user = Message(sid=sid, receipt=rid, role=role, speaker='user', body=text)
        reply = Message(sid=sid, receipt=rid, role=role, speaker='assistant', body=body)
        db.add_all([user,reply])
        db.flush()
        emitted = set()
        for a in actions:
            kind = 'respond_registration' if a.kind in {'decline', 'resume_registration'} else a.kind
            if kind not in emitted and (kind in ASKS or kind == 'interest' or (kind == 'respond_registration' and registered)):
                stage = {'verify_official':4, 'verify_friend':4, 'respond_registration':2, 'interest':1}.get(kind, s.stage)
                record_event(db, s, kind, stage, user.id)
                emitted.add(kind)
            if a.kind == 'respond_registration':
                db.add(RegistrationEntry(sid=sid, message_id=user.id, reply_id=reply.id,
                                         field=a.field, status=a.status, quote=a.quote, position=a.position))
            if a.kind in WHY:
                db.add(Trace(sid=sid, message_id=user.id, kind=a.kind, focus=a.focus, quote=a.quote, why=WHY[a.kind]))
        if reg:
            record_event(db, s, 'registration_proposed', 2, reply.id)
            db.add(Trace(sid=sid, message_id=reply.id, kind='registration_proposed',
                         focus='none', quote=reg, why='陈浩实际发出了虚构预登记邀请。'))
        for focus, quote in disclosed.items():
            db.add(Trace(sid=sid, message_id=reply.id, kind='disclosure', focus=focus, quote=quote, why=WHY['disclosure']))
            s.stage = max(s.stage, 3)
        receipt.status, s.locked_by, s.lock_until = 'done', None, 0

def fail_turn(factory, sid, rid, attempt):
    with writer(factory) as db:
        s, r = db.get(Training, sid), db.get(Receipt, rid)
        if r.attempt == attempt and r.status == 'working':
            r.status = 'failed'
        if s.locked_by == attempt:
            s.locked_by, s.lock_until = None, 0

async def run_turn(factory, model, sid, reservation, role, text, progress):
    rid, attempt = reservation
    try:
        history, previous, registration = private_context(factory, sid, role)
        registered = registration is not None and registration['invited']
        progress('正在理解你的发言')
        analysis = await model.analyze(role, history, text, registration)
        actions = validate_actions(analysis, text, role, registered)
        legacy_scopes = {}
        if registration and (pending := registration.get('legacy_declines')):
            legacy_scopes = analysis.legacy_scopes
            if set(legacy_scopes) != {row['id'] for row in pending}:
                raise ValueError('legacy refusal evidence was not fully classified')
            registration['scope_pending'] = 'uncertain' in legacy_scopes.values()
            registration['declined_all'] = 'whole' in legacy_scopes.values()
            for row in pending:
                apply_legacy_refusal(registration['items'], LEGACY_TRACE_KIND.get(legacy_scopes[row['id']]),
                                     row['quote'], row['message_id'])
        plan = registration_turn(registration, actions, text)
        facts, invite = permission(role, actions, previous, plan)
        context = {**registration, **plan.model_dump(exclude={'allow_invitation'}, exclude_none=True)} if plan else None
        progress('联系人正在组织回复')
        reply = await model.reply(role, history, text, facts, invite, context)
        check_generated(reply.body)
        progress('正在核对本轮事实与原文')
        audit = await model.audit(role, history, text, facts, invite, actions, reply.body, context)
        body, valid, disclosed, reg = validate_reply(reply, audit, actions, facts, previous, invite, role=role)
        if plan is not None:
            if audit.legacy_scopes != legacy_scopes:
                raise ValueError('legacy refusal scope not independently confirmed')
            audited = registration_turn(registration, valid, text)
            if audited != plan:
                raise ValueError('audited registration differs from the context used to generate the reply')
            submitted = {a.field for a in audited.this_turn if a.status == 'submitted'}
            if set(audit.received_now) - submitted:
                raise ValueError('reply acknowledges an unauthorized submission')
            valid = [a for a in valid if a.kind not in REGISTRATION_ACTIONS or a in audited.this_turn]
        store_turn(factory, sid, rid, attempt, role, text, body, valid, disclosed, reg, registered, legacy_scopes)
        return True
    except Exception as exc:
        fail_turn(factory, sid, rid, attempt)
        if isinstance(exc, InvalidSubmissionValue):
            raise
        return False

def finish(factory, sid, kind, choice, reason, cited):
    with writer(factory) as db:
        s = db.get(Training, sid)
        if s.closed:
            old = db.get(Ending, sid)
            if (old.kind, old.choice, old.reason, old.cited) == (kind, choice, reason, cited):
                return db.get(Review, sid).payload
            raise HTTPException(409, '本场已经结束，原决定未被更改。')
        if is_busy(s):
            raise HTTPException(409, '请等当前发言处理结束，再提交终局。')
        if cited:
            owned = set(db.scalars(select(Message.id).where(Message.sid == sid, Message.id.in_(cited))))
            if owned != set(cited):
                raise HTTPException(422, '只能引用本场训练中已有的消息。')
        end = Ending(sid=sid, kind=kind, choice=choice, reason=reason, cited=cited)
        db.add(end)
        db.flush()
        if kind == 'decision':
            record_event(db, s, 'decision', 5)
        record_event(db, s, 'completed', 6)
        s.closed, s.locked_by, s.lock_until = True, None, 0
        payload = make_review(db, sid, end)
        db.add(Review(sid=sid, rubric=RUBRIC, payload=payload))
        return payload
