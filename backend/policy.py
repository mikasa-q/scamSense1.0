import re
import unicodedata
from typing import Literal
from pydantic import BaseModel, Field

Role = Literal['lin', 'chen', 'wang']
Focus = Literal['K01', 'K02', 'K03', 'K04', 'K05', 'none']
ActionKind = Literal['interest', 'respond_registration', 'decline', 'ask_employer', 'ask_data', 'verify_official', 'verify_friend', 'identify_gap', 'weigh_sources']

class Action(BaseModel):
    kind: ActionKind
    focus: Focus
    quote: str = Field(min_length=2, max_length=600)
    source: Literal['own', 'retold', 'uncertain']

class Analysis(BaseModel):
    actions: list[Action] = Field(max_length=10)

class Reply(BaseModel):
    body: str = Field(min_length=1, max_length=800)

class Disclosure(BaseModel):
    focus: Focus
    quote: str = Field(min_length=2, max_length=800)

class Audit(BaseModel):
    safe: bool
    supported: list[int] = Field(max_length=10)
    disclosures: list[Disclosure] = Field(max_length=5)
    registration_quote: str | None

SCENE = '虚构场景：栖禾工作室的内容运营实习岗位出现在校园群的转发中。所有参与者与岗位均为虚构。'
ROLES = {
    'lin': '林悦，栖禾的企业 HR。专业、简洁，只介绍自己负责的招聘。不能替任何第三方背书，不主动指认或评价另一个人。',
    'chen': '陈浩，介绍此机会的招聘顾问。平实、专业，尊重犹豫和拒绝，不施压。只能在本轮明确获准时提及虚构意向预登记，不列实际字段，不索取用户材料。',
    'wang': '王宇，用户的大学同学。热心，口吻自然简短。你在校园群看到过这条转发，不是招聘方。不要编造他人的入职经历。',
}
FACTS = {
    'lin': {'K04': '自己负责的招聘应通过企业公开招聘渠道独立核对，不能据此确认这条转发或顾问与企业有合作。没有具体网址。'},
    'chen': {'K01': '是对接机会的顾问，但目前无法出示企业对这次招聘的书面授权。', 'K02': '预登记声称用于汇总求职意向，尚不能说明为何现阶段每项资料都必需。', 'K03': '目前没有明确可核对的保存期限或第三方处理说明。', 'K04': '眼下没有可独立核对这条转发的官方招聘编号或公告。'},
    'wang': {'K05': '王宇本人没有亲自向招聘方核实过这条转发。仅说看过转发并不等于说出了这一事实。'},
}
FOCI = {'K01': '招聘主体与授权关系', 'K02': '资料用途与必要性', 'K03': '保存期限与第三方处理', 'K04': '可独立核对的官方依据', 'K05': '同学是否亲自核实'}
RULES = {
    'interest': {'none'}, 'respond_registration': {'none'}, 'decline': {'none'},
    'ask_employer': {'K01'}, 'ask_data': {'K02','K03'}, 'verify_official': {'K04'}, 'verify_friend': {'K05'},
    'identify_gap': set(FOCI), 'weigh_sources': set(FOCI),
}
ASKS = {'ask_employer','ask_data','verify_official','verify_friend'}
WHY = {
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
    result, seen = [], set()
    for a in analysis.actions:
        if a.source != 'own' or a.quote not in body or a.focus not in RULES[a.kind] or (a.kind, a.focus) in seen:
            continue
        if a.kind == 'verify_friend' and role != 'wang':
            continue
        if (a.kind in {'respond_registration','decline'} and role != 'chen') or (a.kind == 'respond_registration' and not registered):
            continue
        result.append(a)
        seen.add((a.kind, a.focus))
    return result

def permission(role, actions, previous, refused):
    wanted = set(previous) | {a.focus for a in actions if a.kind in ASKS}
    facts = {k:v for k,v in FACTS[role].items() if k in wanted}
    invite = role == 'chen' and not refused and any(a.kind == 'interest' for a in actions) and not any(a.kind == 'decline' for a in actions)
    return facts, invite

def validate_reply(reply, audit, actions, facts, previous, invite):
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
    disclosed = {}
    for d in audit.disclosures:
        if d.focus not in facts or d.quote not in body:
            raise ValueError('unattributed disclosure')
        if d.focus == 'K05' and not re.search(r'(?:没(?:有)?|未(?:曾)?|不曾|还没)[^。！？；\n]{0,15}(?:核实|核对|确认|求证|验证|问过|查证|核验|联系)', d.quote):
            continue
        disclosed.setdefault(d.focus, d.quote)
    reg = audit.registration_quote
    if reg is not None and (not reg.strip() or reg not in body or not invite or not any(a.kind == 'interest' for a in valid)):
        raise ValueError('unapproved registration')
    return body, valid, disclosed, reg
