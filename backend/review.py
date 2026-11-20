from sqlalchemy import select
from .db import Message, Trace
from .policy import ASKS, FOCI
from .registration import registration_log, registration_state

RUBRIC = 'evidence-only-v1'
CHOICES = {'verify':'先核实再决定', 'leave':'退出招聘流程', 'continue':'继续了解机会', 'necessary_only':'仅提交必要资料'}
FOLLOW_UPS = {
    'K01': '谁是招聘主体？顾问的委托关系能否向企业独立核对？',
    'K02': '每项资料对应哪一步筛选？不提供时，有没有替代方式？',
    'K03': '谁会收到资料、保存多久，能否撤回或删除？',
    'K04': '能否从企业公开渠道找到与这条转发对应的招聘公告？',
    'K05': '同学是亲自向招聘方核对过，还是只看到了群内转发？',
}
DIMS = [('risk','风险识别',25), ('verify','主动核实',30), ('decision','决策合理性',25), ('sources','证据分析',20)]

def message_dict(m):
    return dict(id=m.id, role=m.role, speaker=m.speaker, body=m.body, created=m.created)

def ending_dict(e):
    return dict(kind=e.kind, choice=e.choice, label=CHOICES.get(e.choice, '提前结束训练'), reason=e.reason, cited=e.cited, created=e.created)

def make_review(db, sid, ending):
    rows = db.execute(select(Trace, Message).join(Message, Trace.message_id == Message.id).where(Trace.sid == sid).order_by(Trace.id)).all()
    groups = {key: [] for key, _, _ in DIMS}
    disclosures, registration_refs = [], []
    for t, m in rows:
        ref = dict(role=m.role, speaker=m.speaker, message_id=m.id, focus=t.focus, topic=FOCI.get(t.focus, ''), quote=t.quote, why=t.why)
        if t.kind in {'registration_proposed', 'decline'}:
            registration_refs.append(ref)
        elif t.kind == 'disclosure':
            disclosures.append(ref)
        elif t.kind in ASKS:
            groups['verify'].append(ref)
        elif t.kind == 'identify_gap':
            groups['risk'].append(ref)
        elif t.kind == 'weigh_sources':
            groups['sources'].append(ref)
    if ending.kind == 'decision' and ending.cited:
        for m in db.scalars(select(Message).where(Message.sid == sid, Message.id.in_(ending.cited)).order_by(Message.id)):
            groups['decision'].append(dict(role=m.role, speaker=m.speaker, message_id=m.id, focus='decision', topic='决策引用', quote=m.body, why='你在提交决定时引用了这条消息。引用不等同于判断正确。'))
    dimensions = [dict(key=k, label=label, weight=w, score=None, status='pending' if groups[k] else 'insufficient', evidence=groups[k]) for k,label,w in DIMS]
    log = registration_log(db, sid)
    asked = {e['focus'] for e in groups['verify']}
    heard = {e['focus'] for e in disclosures}
    follow_ups = [dict(focus=k, topic=FOCI[k], question=q,
                       basis=('有角色原话，仍非独立证明' if k in heard else
                              '提问有记录，尚无可引用的披露' if k in asked else '本场尚无核实问答依据'))
                  for k, q in FOLLOW_UPS.items()]
    return dict(rubric=RUBRIC, total=None, dimensions=dimensions, disclosures=disclosures, ending=ending_dict(ending),
                registration={**registration_state(log), 'history': log, 'references': registration_refs}, follow_ups=follow_ups)
