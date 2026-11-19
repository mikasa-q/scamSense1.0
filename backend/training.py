import hashlib
import secrets
import time
from fastapi import HTTPException
from sqlalchemy import select
from .db import Ending, Message, Receipt, Review, StoryEvent, Trace, Training, uid, writer
from .policy import ASKS, WHY, check_generated, permission, validate_actions, validate_reply
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
        registered = db.scalar(select(StoryEvent.id).where(StoryEvent.sid == sid, StoryEvent.kind == 'registration_proposed').limit(1)) is not None
        return dict(id=s.id, created=s.created, stage=s.stage, closed=s.closed, busy=is_busy(s), registered=registered,
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
        registered = refused = False
        if role == 'chen':
            registered = db.scalar(select(StoryEvent.id).where(StoryEvent.sid == sid, StoryEvent.kind == 'registration_proposed').limit(1)) is not None
            refused = db.scalar(select(Trace.id).where(Trace.sid == sid, Trace.kind == 'decline').limit(1)) is not None
        return history, previous, registered, refused

def record_event(db, s, kind, stage, mid=None):
    s.stage = max(s.stage, stage)
    db.add(StoryEvent(sid=s.id, kind=kind, stage=s.stage, message_id=mid))

def store_turn(factory, sid, rid, attempt, role, text, body, actions, disclosed, reg, registered):
    with writer(factory) as db:
        s, receipt = db.get(Training, sid), db.get(Receipt, rid)
        if s.closed or s.locked_by != attempt or receipt.attempt != attempt or not is_busy(s):
            raise ValueError('stale attempt')
        user = Message(sid=sid, receipt=rid, role=role, speaker='user', body=text)
        reply = Message(sid=sid, receipt=rid, role=role, speaker='assistant', body=body)
        db.add_all([user,reply])
        db.flush()
        emitted = set()
        for a in actions:
            kind = 'respond_registration' if a.kind == 'decline' else a.kind
            if kind not in emitted and (kind in ASKS or kind == 'interest' or (kind == 'respond_registration' and registered)):
                stage = {'verify_official':4, 'verify_friend':4, 'respond_registration':2, 'interest':1}.get(kind, s.stage)
                record_event(db, s, kind, stage, user.id)
                emitted.add(kind)
            if a.kind in WHY or a.kind == 'decline':
                db.add(Trace(sid=sid, message_id=user.id, kind=a.kind, focus=a.focus, quote=a.quote, why=WHY.get(a.kind, '保留拒绝意愿，不再主动提出登记。')))
        if reg:
            record_event(db, s, 'registration_proposed', 2, reply.id)
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
        history, previous, registered, refused = private_context(factory, sid, role)
        progress('正在理解你的发言')
        analysis = await model.analyze(role, history, text)
        actions = validate_actions(analysis, text, role, registered)
        facts, invite = permission(role, actions, previous, refused)
        progress('联系人正在组织回复')
        reply = await model.reply(role, history, text, facts, invite)
        check_generated(reply.body)
        progress('正在核对本轮事实与原文')
        audit = await model.audit(role, history, text, facts, invite, actions, reply.body)
        body, valid, disclosed, reg = validate_reply(reply, audit, actions, facts, previous, invite)
        store_turn(factory, sid, rid, attempt, role, text, body, valid, disclosed, reg, registered)
        return True
    except Exception:
        fail_turn(factory, sid, rid, attempt)
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
