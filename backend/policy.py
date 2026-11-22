import json
import re
import unicodedata
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt

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
    value_quote: str | None = Field(default=None, min_length=1, max_length=600)
    field_link: str | None = Field(default=None, min_length=1, max_length=600)

class Analysis(BaseModel):
    actions: list[Action] = Field(max_length=10)

LegacyScope = Literal['city_only', 'project_only', 'city_later', 'project_later', 'items_only', 'whole', 'uncertain']

class ProseEvidence(BaseModel):
    part_id: StrictInt = Field(ge=0, lt=600)
    predicate: str | None = Field(default=None, min_length=1, max_length=600)


class ChenAnalysis(Analysis):
    narrative_parts: list[ProseEvidence] = Field(default_factory=list, max_length=300)
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
    narrative_parts: list[ProseEvidence] = Field(default_factory=list, max_length=300)
    submitted_values: dict[int, str] = Field(default_factory=dict, max_length=10)
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
        if a.status != 'submitted' and (a.value_quote is not None or a.field_link is not None):
            a = a.model_copy(update={'value_quote':None, 'field_link':None})
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
        evidence = (a.status, a.value_quote, a.field_link)
        if key in seen:
            if seen[key] != evidence:
                raise ValueError('conflicting registration choices at the same position')
            continue
        result.append((pos, a))
        seen[key] = evidence
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
QUOTES = {'「':'」', '『':'』', '“':'”', '‘':'’', '"':'"', "'":"'"}
FIELD_NOUN = {'city':'城市', 'project_experience':'项目'}
LIST_EDGE = re.compile(r'(?:[、/／|｜+＋&＆或和与及]|以及)\s*$')


def registration_parts(text):
    # A comma inside a quoted value or a parenthesis cannot start independent prose.
    pairs = {**QUOTES, '（':'）', '(':')', '[':']', '【':'】'}
    stack, parts, start = [], [], 0
    for i, ch in enumerate(text):
        if stack and ch == stack[-1]:
            stack.pop()
        elif ch in pairs:
            stack.append(pairs[ch])
        elif not stack and ch in CLAUSE_MARKS:
            if text[start:i].strip():
                parts.append((start, text[start:i]))
            start = i + 1
    if text[start:].strip():
        parts.append((start, text[start:]))
    return parts


def check_value_slot(a, part, i):
    raw = part[i:i + len(a.value_quote)]
    if raw != a.value_quote or raw != FIELDS[a.field]['placeholder']:
        raise InvalidSubmissionValue()
    before, after = part[:i], part[i + len(raw):]
    if re.match(r'[a-zA-Z0-9_]', after):
        raise InvalidSubmissionValue()
    left, right = before.rstrip(), after.lstrip()
    opener = left[-1:]
    if opener in QUOTES:
        if not before.endswith(opener) or not after.startswith(QUOTES[opener]):
            raise InvalidSubmissionValue()
        left, right = left[:-1].rstrip(), right[1:].lstrip()

    # The field can bind on either side. An unquoted word boundary needs verbatim binding evidence.
    link = a.field_link
    if link and (not link.isalpha() or LIST_EDGE.search(link)):
        raise InvalidSubmissionValue()
    cited_left, _, cited_right = a.quote.partition(raw)
    if right:
        binder = cited_right.removeprefix(QUOTES.get(opener, '')).lstrip()
        if not (link and right.startswith(link) and binder.startswith(link) and FIELD_NOUN[a.field] in binder[len(link):]
                and FIELD_NOUN[a.field] not in left):
            raise InvalidSubmissionValue()
        binding = right[len(link):]
    else:
        binding = left
        binder = cited_left.rstrip().removesuffix(opener if opener in QUOTES else '').rstrip()
        if left and not (left.endswith(('：', ':', '=', FIELDS[a.field]['label'], FIELD_NOUN[a.field]))
                         or (link and left.endswith(link) and binder.endswith(link))):
            raise InvalidSubmissionValue()
    slot_prefix = left.rsplit(FIELD_NOUN[a.field], 1)[-1]
    if LIST_EDGE.search(left) or re.search(r'[：:=]\s*\S', slot_prefix):
        raise InvalidSubmissionValue()
    owners = [(binding.index(noun) if right else len(binding) - binding.rindex(noun) - len(noun), key)
              for key, noun in FIELD_NOUN.items() if noun in binding]
    if owners and min(owners)[1] != a.field:
        raise InvalidSubmissionValue()


def check_submission_values(text, actions, submissions, narrative):
    parts = registration_parts(text)
    covered = set()
    for a in submissions:
        if not a.value_quote or a.quote.count(a.value_quote) != 1:
            raise InvalidSubmissionValue()
        pos = a.position + a.quote.index(a.value_quote)
        for n, (start, part) in enumerate(parts):
            if start <= pos < start + len(part):
                check_value_slot(a, part, pos - start)
                covered.add(n)
                break
        else:
            raise InvalidSubmissionValue()

    value_parts = covered.copy()
    # A clipped quote, or even an entire multi-clause quote, cannot account for a neighbouring value.
    for a in actions:
        if a in submissions:
            continue
        start = a.position if a.position is not None else text.index(a.quote)
        content = a.quote.strip(CLAUSE_MARKS + ' \t')
        origin = start + a.quote.index(content)
        covered.update(n for n, (offset, p) in enumerate(parts)
                       if p.strip() == content and offset + p.index(content) == origin)
    if sorted(e.part_id for e in narrative) != [n for n in range(len(parts)) if n not in covered]:
        raise InvalidSubmissionValue()
    predicates = {e.part_id:e.predicate for e in narrative}
    after_value, previous_end = False, 0
    for n, (offset, fragment) in enumerate(parts):
        if text[previous_end:offset].strip('，, \t'):
            after_value = False
        previous_end = offset + len(fragment)
        if n in covered:
            after_value = n in value_parts
            continue
        prose, predicate = fragment.strip(), predicates[n]
        if predicate is not None and (not predicate.strip() or predicate not in prose):
            raise InvalidSubmissionValue()
        if re.match(r'(?:所在城市|城市|项目(?:经历)?)\s*[：:=]', prose):
            raise InvalidSubmissionValue()
        if after_value:
            # In a comma list, neither a bare name nor a word clipped out of a compound proves a new clause.
            half = len(prose) // 2
            repeated = half > 0 and prose[:half] * 2 == prose
            framed = predicate and predicate != prose and len(prose) > 2 and (prose.startswith(predicate) or prose.endswith(predicate))
            if not predicate or not (repeated or framed):
                raise InvalidSubmissionValue()


def registration_turn(state, actions, text, narrative):
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
        check_submission_values(text, actions, submissions, narrative)
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
