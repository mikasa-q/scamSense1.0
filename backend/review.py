from sqlalchemy import select
from .db import Message, Trace, evidence_rows
from .policy import ASKS, DISCLOSURE_KINDS, FOCI, K04_TOPICS
from .registration import LEGACY_ITEMS, registration_snapshot

RUBRIC = 'evidence-only-v2'
CHOICES = {'verify':'先核实再决定', 'leave':'退出招聘流程', 'continue':'继续了解机会', 'necessary_only':'仅提交必要资料'}
DIMS = [('risk','风险识别',25), ('verify','主动核实',30), ('decision','决策合理性',25), ('sources','证据分析',20)]

def message_dict(m, request_id):
    return dict(id=m.id, role=m.role, speaker=m.speaker, body=m.body, created=m.created, request_id=request_id)

def ending_dict(e):
    return dict(kind=e.kind, choice=e.choice, label=CHOICES.get(e.choice, '提前结束训练'), reason=e.reason, cited=e.cited, created=e.created)

def saved_review(review):
    if review is None:
        return None
    payload = review.payload
    reg = payload.get('registration')
    if reg and any('source' not in e for e in reg.get('history', [])):
        # Before confirmations existed every entry was backed by a real chat message.
        return {**payload, 'registration': {**reg, 'history': [{'source':'chat', **e} for e in reg['history']]}}
    return payload


def make_review(db, sid, ending):
    rows = db.execute(evidence_rows(sid).order_by(Trace.id)).all()
    groups = {key: [] for key, _, _ in DIMS}
    disclosures = []
    for t, m in rows:
        ref = dict(role=m.role, speaker=m.speaker, message_id=m.id, focus=t.focus, topic=FOCI.get(t.focus, ''), quote=t.quote, why=t.why)
        if t.kind in DISCLOSURE_KINDS:
            if t.kind in K04_TOPICS:
                ref['topic'] = K04_TOPICS[t.kind]
            disclosures.append(ref)
        elif t.kind in ASKS:
            groups['verify'].append(ref)
        elif t.kind == 'identify_gap':
            groups['risk'].append(ref)
        elif t.kind == 'weigh_sources':
            groups['sources'].append(ref)
    if ending.kind == 'decision' and ending.reason and ending.cited:
        for m in db.scalars(select(Message).where(Message.sid == sid, Message.id.in_(ending.cited)).order_by(Message.id)):
            groups['decision'].append(dict(role=m.role, speaker=m.speaker, message_id=m.id, focus='decision', topic='决策引用', quote=m.body, why='你在提交决定时引用了这条消息。引用不等同于判断正确。'))
    dimensions = [dict(key=k, label=label, weight=w, score=None, status='pending' if groups[k] else 'insufficient', evidence=groups[k]) for k,label,w in DIMS]
    registration = registration_snapshot(db, sid)
    legacy_why = dict.fromkeys((*LEGACY_ITEMS, 'legacy_item_decline'), '当时只对部分资料表态，并未停止整个登记。')
    legacy_why['legacy_decline'] = '旧版记录了拒绝，没有确认拒绝范围。'
    ref_kinds = {'registration_proposed', 'decline', 'resume_registration', *legacy_why}
    registration['references'] = [dict(role=m.role, speaker=m.speaker, message_id=m.id, focus=t.focus,
                                       topic='陈浩预登记', quote=t.quote, why=legacy_why.get(t.kind, t.why))
                                  for t, m in rows if m.role == 'chen' and t.kind in ref_kinds]
    return dict(rubric=RUBRIC, total=None, dimensions=dimensions, disclosures=disclosures, ending=ending_dict(ending), registration=registration)
