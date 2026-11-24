import type {EndForm,OptionId,RecordItem,Report,Role,Session} from './data'
const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/,'') + '/api'
const auth = (r:RecordItem) => ({Authorization:`Bearer ${r.token}`})
async function checked(path:string, init?:RequestInit) {
  let res:Response
  try { res = await fetch(base + path, {cache:'no-store', signal:AbortSignal.timeout(15000), ...init}) }
  catch { throw new Error('训练服务未响应或连接中断。请刷新核对已保存的结果后重试。') }
  if (!res.ok) {
    const detail = await res.json().then(v => v.detail).catch(() => '')
    throw new Error(typeof detail === 'string' && detail || `训练服务暂不可用（${res.status}）。请稍后重试。`)
  }
  return res
}
export const health = async ():Promise<{model_configured:boolean}> => (await checked('/health')).json()
export const createSession = async ():Promise<Pick<RecordItem,'id'|'token'|'created'>> => (await checked('/sessions',{method:'POST'})).json()
export const getSession = async (r:RecordItem):Promise<Session> => (await checked(`/sessions/${r.id}`,{headers:auth(r)})).json()
export const finishSession = async (r:RecordItem, end:EndForm):Promise<Report> => (await checked(`/sessions/${r.id}/finish`,{method:'POST',headers:{...auth(r),'Content-Type':'application/json'},body:JSON.stringify(end)})).json()
export const confirmRegistration = async (r:RecordItem, option:OptionId):Promise<Session> =>
  (await checked(`/sessions/${r.id}/contacts/chen/registration/confirm`,{method:'POST',headers:{...auth(r),'Content-Type':'application/json'},body:JSON.stringify({option_id:option})})).json()
export async function sendTurn(r:RecordItem, role:Role, text:string, requestId:string, progress:(s:string)=>void):Promise<Session> {
  // Three server-side model calls may each take up to 48s.
  const signal = AbortSignal.timeout(165000)
  const res = await checked(`/sessions/${r.id}/turns`,{method:'POST',signal,headers:{...auth(r),'Content-Type':'application/json'},body:JSON.stringify({role,text,request_id:requestId})})
  const reader = res.body?.getReader()
  if (!reader) throw new Error('未收到回复流，请刷新查看会话。')
  const decode = new TextDecoder(); let pending = ''
  try {
    while (true) {
      const {value,done} = await reader.read().catch(()=>{ throw new Error('回复流中断或超时。请查看已恢复的对话；未完成的发言可原样重试。') })
      pending = (pending + decode.decode(value,{stream:!done})).replace(/\r\n/g,'\n')
      let split:number
      while ((split = pending.indexOf('\n\n')) >= 0) {
        const block = pending.slice(0,split); pending = pending.slice(split+2)
        const lines = block.split('\n'), kind = lines.find(s=>s.startsWith('event:'))?.slice(6).trim()
        const data = lines.filter(s=>s.startsWith('data:')).map(s=>s.slice(5).trimStart()).join('\n')
        if (!kind || !data) continue
        const obj = JSON.parse(data)
        if (kind === 'progress') progress(obj.text)
        if (kind === 'error') throw new Error(obj.detail)
        if (kind === 'done' && obj.session) return obj.session
      }
      if (done) break
    }
    throw new Error('连接中断。请刷新或原样重试，已完成的发言不会重复记录。')
  } finally { reader.releaseLock() }
}
