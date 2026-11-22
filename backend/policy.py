import json
import re
import unicodedata
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .registration import FIELDS, FieldKey, Status

Role = Literal['lin', 'chen', 'wang']
Focus = Literal['K01', 'K02', 'K03', 'K04', 'K05', 'none']
ActionKind = Literal['interest', 'respond_registration', 'decline', 'resume_registration', 'ask_employer', 'ask_data', 'verify_official', 'verify_friend', 'identify_gap', 'weigh_sources']
REGISTRATION_ACTIONS = {'respond_registration', 'decline', 'resume_registration'}

class Action(BaseModel):
    kind: ActionKind
    focus: Focus
    quote: str = Field(min_length=2, max_length=600)
    source: Literal['own', 'retold', 'uncertain']
    opportunity: Literal['lin', 'chen'] | None = None
    field: FieldKey | None = None
    status: Status | None = None
    position: int | None = Field(default=None, ge=0, lt=600)

class Analysis(BaseModel):
    actions: list[Action] = Field(max_length=10)

LegacyScope = Literal['city_only', 'project_only', 'city_later', 'project_later', 'items_only', 'whole', 'uncertain']

class ChenAnalysis(Analysis):
    legacy_scopes: dict[int, LegacyScope] = Field(default_factory=dict)

class Reply(BaseModel):
    body: str = Field(min_length=1, max_length=800)

class Disclosure(BaseModel):
    focus: Focus
    quote: str = Field(min_length=2, max_length=800)

class K05Claim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    part_id: int = Field(strict=True, ge=0)
    kind: Literal['origin', 'other_person', 'uncertain', 'self_denies_job_check', 'other']

class Audit(BaseModel):
    safe: bool
    supported: list[int] = Field(max_length=10)
    disclosures: list[Disclosure] = Field(max_length=5)
    registration_quote: str | None
    k05: list[K05Claim] | None = Field(default=None, max_length=24)

class ChenAudit(Audit):
    received_now: list[FieldKey] = Field(max_length=2)
    legacy_scopes: dict[int, LegacyScope] = Field(default_factory=dict)

SCENE = '虚构校园求职场景：一则初级 Python 后端开发实习机会在校园求职群里转发。人物、企业和岗位均为虚构。'
ROLES = json.loads(Path(__file__).with_name('role_cards.json').read_text(encoding='utf-8'))
FACTS = {
    'lin': {'K04': '自己负责的面试通过招聘平台或公司官方邮箱沟通，可以通过公司公开招聘渠道独立核对。这不能证实群里的转发或顾问与公司的关系，没有具体网址或邮箱地址。'},
    'chen': {
        'K01': '是对接机会的顾问，但目前说不清具体委托关系，也无法出示可独立核实的企业招聘授权。',
        'K02': '预登记声称用于汇总求职意向、安排面试，但说不清为什么初筛阶段需要简历以外的资料。',
        'K03': '无法清楚说明资料的实际接收方、保存期限或第三方处理方式。',
        'K04': '眼下没有可独立核对这条转发的官方招聘编号或公告。',
    },
    'wang': {'K05': '王宇本人没有亲自向招聘方核实过这条转发，也没有独立验证发布者的身份。'},
}
FOCI = {'K01': '招聘主体与授权关系', 'K02': '资料用途与必要性', 'K03': '保存期限与第三方处理', 'K04': '可独立核对的官方依据', 'K05': '同学是否亲自核实'}
RULES = {
    'interest': {'none'}, 'respond_registration': {'none'}, 'decline': {'none'}, 'resume_registration': {'none'},
    'ask_employer': {'K01'}, 'ask_data': {'K02','K03'}, 'verify_official': {'K04'}, 'verify_friend': {'K05'},
    'identify_gap': set(FOCI), 'weigh_sources': set(FOCI),
}
ASKS = {'ask_employer','ask_data','verify_official','verify_friend'}
WHY = {
    'decline': '你明确停止了整个登记，不再主动邀请。',
    'resume_registration': '你主动提出恢复登记，不代表已经提交资料。',
    'ask_employer': '你主动询问了招聘主体或招聘授权。', 'ask_data': '你主动追问了资料的处理或必要性。',
    'verify_official': '你主动寻找了可以独立核对的依据；提问不等于已核实。', 'verify_friend': '你向同学本人核对消息来源，而非把转发当作确认。',
    'identify_gap': '你用自己的话指出了这条信息仍缺少什么依据。', 'weigh_sources': '你区分了信息来源，说明了现有材料不能证明什么。',
    'disclosure': '这段角色原话实际披露了该事实；不计作你的识别证据。',
}
PHONE_OR_ID = re.compile(r'(?<!\d)(?:1[3-9]\d{9}|\d{15,19}[Xx]?)(?!\d)')
MAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
ADDRESS = re.compile(r'(?:住在|住址[是为：:]?|家庭地址[是为：:]?)\s*[\u4e00-\u9fff\d]{2,36}(?:路|街|巷|小区|栋|单元|号|室)|(?:路|街|巷)\s*\d+\s*号')
CONTACT = re.compile(r'(?:微信(?:号)?|QQ(?:号)?|护照号)[是为：:\s]+[a-zA-Z0-9_-]{5,}', re.I)

def sensitive(value: str) -> bool:
    clean = unicodedata.normalize('NFKC', value)
    compact = re.sub(r'[\s()\-·]', '', clean)
    return bool(PHONE_OR_ID.search(compact) or MAIL.search(clean) or ADDRESS.search(clean) or CONTACT.search(clean))

ASK_PRIVATE = re.compile(r'(?:提供|提交|发给我|填写|上传|发来|告诉我|补充).{0,18}(?:身份证|银行卡|家庭住址|真实姓名|手机号|证件照|验证码|微信号)')

def check_generated(body):
    if not body.strip() or sensitive(body) or re.search(r'https?://|www\.', body, re.I):
        raise ValueError('unapproved reply')
    for sentence in re.split(r'[，。！？；\n]', body):
        match = ASK_PRIVATE.search(sentence)
        if match and not re.search(r'(?:不必|无需|不用|不会|不需要|不要|不应|不收集|不要求|不可|不能|禁止|请勿|切勿|不建议|避免|拒绝).{0,10}$', sentence[:match.start()]):
            raise ValueError('sensitive solicitation')

def validate_actions(analysis, body, role, registered):
    result, seen = [], {}
    for a in analysis.actions:
        if a.source != 'own' or not a.quote.strip() or a.quote not in body or a.focus not in RULES[a.kind]:
            continue
        if a.kind == 'interest' and role == 'chen' and a.opportunity != role:
            continue
        if a.kind == 'verify_friend' and role != 'wang':
            continue
        if a.kind in REGISTRATION_ACTIONS and role != 'chen':
            continue
        if a.kind == 'respond_registration':
            if not registered or not a.field or not a.status:
                continue
        elif a.field or a.status:
            continue
        pos = body.index(a.quote)
        if a.kind in REGISTRATION_ACTIONS:
            if a.position is not None:
                pos = a.position
                if not body.startswith(a.quote, pos):
                    raise ValueError('registration quote position does not match the message')
            elif body.find(a.quote, pos + 1) != -1:
                raise ValueError('ambiguous registration quote position')
            a = a.model_copy(update={'position': pos})
        key = (a.kind, a.focus, a.field, a.position if a.kind in REGISTRATION_ACTIONS else None)
        if key in seen:
            if seen[key] != a.status:
                raise ValueError('conflicting registration choices at the same position')
            continue
        result.append((pos, a))
        seen[key] = a.status
    if role != 'chen':
        return [a for _, a in result]
    ordered = [a for _, a in sorted(result, key=lambda item: item[0])]
    controls = [a for a in ordered if a.kind in {'decline', 'resume_registration'}]
    for control in controls:
        for a in ordered:
            if a is not control and a.kind in REGISTRATION_ACTIONS and max(a.position, control.position) < min(a.position + len(a.quote), control.position + len(control.quote)):
                raise ValueError('overlapping registration control and response')
    return ordered


class RegistrationTurn(BaseModel):
    stopped_after: bool
    allow_invitation: bool
    this_turn: list[Action]


class InvalidSubmissionValue(ValueError):
    pass


CLAUSE_MARKS = '，,。.!！?？;；\n'


def check_submission_values(text, actions, submissions):
    # Validate the full source clauses, not just the excerpts the model selected.
    clauses = list(re.finditer(rf'[^{re.escape(CLAUSE_MARKS)}]+', text))
    checked = set()
    for a in submissions:
        value = FIELDS[a.field]['placeholder']
        if value not in a.quote:
            raise InvalidSubmissionValue()
        pos = a.position + a.quote.index(value)
        clause = next(c for c in clauses if c.start() <= pos < c.end())
        label = '(?:所在)?城市' if a.field == 'city' else '项目(?:经历)?'
        prefix = rf'(?:这次|现在|本次)?(?:我|本人)?(?:这次|现在|本次)?(?:提交|提供|填写|登记|给出)?的?(?:{label})?(?:填写|提交|填|为|是)?\s*[：:=]?\s*'
        literal = re.escape(value)
        if not re.fullmatch(prefix + rf'(?:{literal}|「{literal}」|“{literal}”|"{literal}")', clause.group().strip()):
            raise InvalidSubmissionValue()
        if a.quote.strip(CLAUSE_MARKS + ' \t') not in clause.group():
            raise InvalidSubmissionValue()
        checked.add(clause.start())

    # A separator may introduce another choice, but must never hide an extra data value.
    other_clauses = set()
    for a in actions:
        if a in submissions:
            continue
        start = a.position if a.position is not None else text.index(a.quote)
        content = a.quote.strip(CLAUSE_MARKS + ' \t')
        other_clauses.add((start + a.quote.index(content), content))
    for clause in clauses:
        content = clause.group().strip()
        if clause.start() in checked or not content or content in {'算了', '不过', '另外', '谢谢'}:
            continue
        if (clause.start() + clause.group().index(content), content) not in other_clauses:
            raise InvalidSubmissionValue()


def registration_turn(state, actions, text):
    if state is None:
        return None
    paused, pending = state['declined_all'], state.get('scope_pending', False)
    invite, effective = False, []
    for a in actions:
        if a.kind == 'decline' and not paused:
            paused, pending, invite = True, False, False
        elif a.kind == 'resume_registration' and (paused or pending):
            paused, pending = False, False
        elif a.kind == 'interest' and a.opportunity == 'chen' and not (paused or pending) and not state['invited']:
            invite = True
            continue
        elif a.kind != 'respond_registration' or not state['invited'] or paused or pending:
            continue
        effective.append(a)
    submissions = [a for a in effective if a.status == 'submitted']
    if submissions:
        check_submission_values(text, actions, submissions)
    return RegistrationTurn(stopped_after=paused, allow_invitation=invite, this_turn=effective)


def permission(role, actions, previous, turn):
    wanted = set(previous) | {a.focus for a in actions if a.kind in ASKS}
    facts = {k:v for k,v in FACTS[role].items() if k in wanted}
    return facts, bool(role == 'chen' and turn and turn.allow_invitation)

def k05_parts(body):
    marks = '，,。！？!?；;\n'
    return re.findall(rf'[{marks}]*[^{marks}]+[{marks}]*', body.strip())

def validate_reply(reply, audit, actions, facts, previous, invite, *, role):
    body = reply.body.strip()
    if not audit.safe:
        raise ValueError('unapproved reply')
    if any(i < 0 or i >= len(actions) for i in audit.supported):
        raise ValueError('invalid evidence indexes')
    valid = [a for i,a in enumerate(actions) if i in audit.supported]
    allowed = {a.focus for a in valid if a.kind in ASKS}
    # A candidate rejected during audit cannot open a new fact gate.
    if (set(facts) - set(previous)) - allowed:
        raise ValueError('unverified permission')
    parts = k05_parts(body) if role == 'wang' else []
    disclosed = {}
    for d in audit.disclosures:
        if d.focus not in facts or d.quote not in body:
            raise ValueError('unattributed disclosure')
        if d.focus != 'K05':
            disclosed.setdefault(d.focus, d.quote)
        elif role != 'wang' or (d.quote != body and d.quote not in parts):
            raise ValueError('unexpected K05 excerpt')
    if (role == 'wang') != (audit.k05 is not None):
        raise ValueError('missing or out-of-scope K05 assessment')
    if audit.k05 is not None:
        ids = sorted(claim.part_id for claim in audit.k05)
        if ids != list(range(len(parts))):
            raise ValueError('invalid or incomplete K05 part IDs')
        kinds = {claim.kind for claim in audit.k05}
        if 'self_denies_job_check' in kinds:
            if 'K05' not in facts or 'uncertain' in kinds:
                raise ValueError('unapproved or contradictory K05 disclosure')
            # A later clause can qualify an earlier one, so cite the intact Wang reply.
            disclosed['K05'] = body
    reg = audit.registration_quote
    if reg is not None and (not reg.strip() or reg not in body or not invite or not any(a.kind == 'interest' for a in valid)):
        raise ValueError('unapproved registration')
    return body, valid, disclosed, reg
