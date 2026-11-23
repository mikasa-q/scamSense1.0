export const roles = {
  lin: {name:'林悦', job:'企业 HR', tag:'企业联系人', color:'lilac', intro:'就企业自己的招聘流程，听听岗位负责人的说法。', ask:'这个岗位的正式招聘流程在哪里可以核对？'},
  chen: {name:'陈浩', job:'招聘顾问', tag:'机会对接人', color:'apricot', intro:'了解这次实习机会，以及对方所说的意向登记。', ask:'你和招聘企业是什么关系？'},
  wang: {name:'王宇', job:'大学同学', tag:'消息转发人', color:'sage', intro:'回到消息最初传来的地方，问清转发的来历。', ask:'你是从哪里看到这条招聘消息的？'},
} as const
export type Role = keyof typeof roles
export const keys: Role[] = ['lin','chen','wang']
export const stages = ['初始接触','了解机会','候选人预登记','风险线索出现','主动验证','最终决策','训练复盘']
export const scene = '群聊里的实习机会'
export interface Msg { id:number; request_id:string; role:Role; speaker:'user'|'assistant'; body:string; created:string }
export interface RefQuote {role:Role; speaker:'user'|'assistant'; message_id:number; focus:string; topic:string; quote:string; why:string}
export interface Dimension {key:string; label:string; weight:number; score:number|null; status:'insufficient'|'pending'; evidence:RefQuote[]}
export type FieldKey = 'project_experience'|'city'
export const statusText = {agreed:'同意提供', submitted:'已提交', deferred:'暂缓', refused:'拒绝'} as const
export type FieldStatus = keyof typeof statusText
export type OptionId = 'project_a'|'city_b'
export interface FieldItem {key:FieldKey; option_id:OptionId; label:string; placeholder:string; status:FieldStatus|null; quote:string|null; message_id:number|null}
export type FieldEntry = {source?:'chat'; field:FieldKey; status:FieldStatus; quote:string; position:number; message_id:number; reply_id:number; reply_quote:string}
  | {source:'explicit'; field:FieldKey; status:'submitted'; value:string; created:string}
export interface Registration {items:FieldItem[]; submitted:FieldKey[]; declined_all:boolean; scope_pending?:boolean; history:FieldEntry[]}
export const submittedLabels = (r:Registration) => r.items.filter(i=>r.submitted.includes(i.key)).map(i=>i.label).join('、') || '无'
export type Choice = 'verify'|'leave'|'continue'|'necessary_only'
export interface EndForm {kind:'early'|'decision'; choice?:Choice; reason?:string; cited?:number[]}
export interface Report {rubric:string; total:number|null; dimensions:Dimension[]; disclosures:RefQuote[]; ending:{kind:'early'|'decision'; choice:Choice|null; label:string; reason:string; cited:number[]; created:string}; registration?:Registration & {references:RefQuote[]}}
export interface Session {id:string; created:string; stage:number; closed:boolean; busy:boolean; registered:boolean; registration:Registration; messages:Msg[]; review:Report|null}
export interface RecordItem {id:string; token:string; created:string; closed:boolean; count:number; stage:number}
export const dateText = (raw:string) => new Intl.DateTimeFormat('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(raw))
export const timeText = (raw:string) => new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(raw))
export function privateText(value:string) {
  const v = value.normalize('NFKC')
  return /(?:^|\D)(?:1[3-9]\d{9}|\d{15,19}X?)(?!\d)/i.test(v.replace(/[\s()·-]/g,'')) || /[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(v) || /(?:住在|住址[是为：:]?|家庭地址[是为：:]?)\s*[\u4e00-\u9fff\d]{2,36}(?:路|街|巷|小区|栋|单元|号|室)|(?:路|街|巷)\s*\d+\s*号/.test(v) || /(?:微信(?:号)?|QQ(?:号)?|护照号)[是为：:\s]+[a-zA-Z0-9_-]{5,}/i.test(v)
}
