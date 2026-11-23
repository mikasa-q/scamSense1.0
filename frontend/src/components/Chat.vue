<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {ArrowLeft, ArrowRight, BookOpenText, ChevronRight, CircleAlert, Flag, LockKeyhole, MessageCircle, RefreshCw, SendHorizontal, ShieldCheck} from 'lucide-vue-next'
import {keys, roles, scene, stages, timeText, privateText, type OptionId, type Role, type Session, type RecordItem} from '../data'
import {confirmRegistration,getSession,sendTurn} from '../api'
import Portrait from './Portrait.vue'
import EndDialog from './EndDialog.vue'
import RegistrationPanel from './RegistrationPanel.vue'
const props=defineProps<{session:Session; record:RecordItem; role:Role; target:number; configured:boolean|null}>()
const emit=defineEmits<{saved:[s:Session]; reload:[]; check:[]; ended:[]}>()
const visibleMessages=computed(()=>props.session.messages.filter(m=>m.role===props.role))
const roleInfo=computed(()=>roles[props.role]); const text=ref(''), progress=ref(''), failure=ref(''), sending=ref(false)
type Draft = {text:string; id:string}
const lastRequest=ref<Draft|null>(null); const pendingTurn=ref<{role:Role;text:string}|null>(null); const input=ref<HTMLTextAreaElement>(); const scroll=ref<HTMLDivElement>()
const closing=ref<'early'|'decision'|null>(null)
const confirming=ref(false)
const locked=computed(()=>sending.value || confirming.value || props.session.busy)
async function confirm(option:OptionId) {
  if (locked.value || props.session.closed || props.role!=='chen') return
  confirming.value=true; failure.value=''
  try {emit('saved',await confirmRegistration(props.record,option))}
  catch(e) {
    failure.value=(e as Error).message
    try {
      const s=await getSession(props.record); emit('saved',s)
      const item=s.registration.items.find(i=>i.option_id===option)
      if(item && s.registration.submitted.includes(item.key)) failure.value=''
    } catch { /* Keep the original error and allow a safe repeat click. */ }
  }
  finally {confirming.value=false}
}
const poll=window.setInterval(()=>{if(props.session.busy && !sending.value) emit('reload')},2500)
onBeforeUnmount(()=>window.clearInterval(poll))
const threadLink=(role:Role)=>`#/chat/${props.session.id}/${role}`
async function position() {await nextTick(); const target=props.target && document.getElementById(`msg-${props.target}`); if(target) target.scrollIntoView({block:'nearest'}); else if(scroll.value) scroll.value.scrollTop=scroll.value.scrollHeight}
onMounted(position)
const draftKey=(role:Role)=>`scamsense.pending.${props.session.id}.${role}`
function saveDraft(role:Role, draft:Draft|null) {
  try {
    if(draft) sessionStorage.setItem(draftKey(role),JSON.stringify(draft))
    else sessionStorage.removeItem(draftKey(role))
  } catch { /* In-memory retries still work when tab storage is disabled. */ }
}
function reconcile() {
  if(props.session.closed) keys.forEach(role=>saveDraft(role,null))
  const draft=lastRequest.value
  if(!draft) return
  if(props.session.closed || props.session.messages.some(m=>m.role===props.role && m.request_id===draft.id)) {
    saveDraft(props.role,null); lastRequest.value=null; failure.value=''
    if(text.value.trim()===draft.text) text.value=''
  } else if(!props.session.busy && !sending.value && !failure.value) {
    failure.value='尚未找到这条发言的完成记录。可原样重试，不会重复写入。'
  }
}
watch(()=>props.role,role=>{
  text.value=''; failure.value=''; lastRequest.value=null
  try {
    const draft=JSON.parse(sessionStorage.getItem(draftKey(role))||'null')
    if(typeof draft?.id==='string' && typeof draft.text==='string') {lastRequest.value=draft; text.value=draft.text}
  } catch { /* No recoverable draft. */ }
  reconcile()
},{immediate:true})
watch(()=>props.session,reconcile)
watch(()=>[props.role,props.target],position)
watch(()=>[visibleMessages.value.length,progress.value],position)
function suggest(v:string) {
  const draft=text.value ? `${text.value}，${v}` : v
  if(draft.length>600) failure.value='追加后超过 600 字，请先缩短草稿。'
  else {text.value=draft; failure.value=''}
  input.value?.focus()
}
async function send() {
  const body=text.value.trim(); if(!body || locked.value || props.session.closed) return
  if(privateText(body)) { failure.value='请移除疑似真实的个人资料，改用「虚构资料 A」等占位文字。'; return }
  const role=props.role, rid=lastRequest.value?.text===body ? lastRequest.value.id : crypto.randomUUID()
  lastRequest.value={text:body,id:rid}; saveDraft(role,lastRequest.value)
  sending.value=true; failure.value=''; progress.value='正在连接训练服务'; pendingTurn.value={role,text:body}
  try {
    const s=await sendTurn(props.record,role,body,rid,v=>progress.value=v)
    saveDraft(role,null); emit('saved',s)
    if(props.role===role) {text.value=''; lastRequest.value=null}
  } catch(e) {if(props.role===role) failure.value=(e as Error).message; emit('reload'); emit('check')}
  finally {sending.value=false;progress.value='';pendingTurn.value=null; await nextTick();input.value?.focus()}
}
function enter(e:KeyboardEvent) {if(e.key==='Enter' && !e.isComposing && !e.shiftKey && e.keyCode!==229) {e.preventDefault();send()}}
</script>
<template>
  <div class="page-intro compact"><div class="eyebrow"><span></span> PRIVATE CHANNELS &nbsp;/&nbsp; CASE 001</div><div class="title-line"><h1>{{scene}}</h1><span class="stage-pill">S{{session.stage}} · {{stages[session.stage]}}</span></div><p>每位联系人只能看到与你的私聊。用户转述不等于独立核实。</p></div>
  <div v-if="configured===false && !session.closed" class="notice"><CircleAlert :size="18"/><div><b>尚未配置对话模型</b><p>可以浏览训练空间；真实私聊需在后端配置 OpenAI 兼容服务。<a href="#/sample">先看只读示例</a></p></div><button class="icon-button" title="重新检查模型配置" aria-label="重新检查模型配置" @click="emit('check')"><RefreshCw :size="16"/></button></div>
  <div class="chat-layout"><aside class="roster panel"><div class="panel-label">联系人 <span>03</span></div><a v-for="k in keys" :key="k" :href="threadLink(k)" :class="['roster-row',{selected:k===role}]" :aria-current="k===role?'page':undefined" @click="(sending || confirming) && $event.preventDefault()"><Portrait :role="k"/><span><b>{{roles[k].name}}</b><small>{{roles[k].job}}</small></span><ChevronRight :size="15"/></a><div class="roster-foot"><LockKeyhole :size="14"/> 三个独立对话空间</div></aside>
    <section class="thread panel"><div class="thread-head"><Portrait :role="role"/><div><b>{{roleInfo.name}}</b><small>{{roleInfo.job}} · 虚构联系人</small></div><span class="neutral-pill">{{ session.closed?'只读回看':'私聊' }}</span></div>
      <div ref="scroll" class="thread-scroll" role="log" aria-label="私聊记录" aria-live="polite"><div v-if="!visibleMessages.length" class="empty-thread"><span class="empty-icon"><MessageCircle :size="24"/></span><h3>与{{roleInfo.name}}的私聊</h3><p>{{roleInfo.intro}}</p><button v-if="!session.closed" class="prompt-chip" :disabled="locked" @click="suggest(roleInfo.ask)">试着问：{{roleInfo.ask}} <ArrowRight :size="13"/></button></div>
        <div v-for="m in visibleMessages" :id="`msg-${m.id}`" :key="m.id" :class="['message',m.speaker,{highlight:target===m.id}]" tabindex="-1"><small>{{m.speaker==='user'?'你':roleInfo.name}} · {{timeText(m.created)}} <span v-if="target===m.id"> / 复盘引文所在消息</span></small><p>{{m.body}}</p></div>
        <div v-if="sending && pendingTurn?.role===role" class="message user draft-bubble"><small>你 · 待校验，尚未写入</small><p>{{pendingTurn.text}}</p></div><div v-if="locked" class="working"><i></i>{{confirming ? '正在确认虚构资料…' : progress || '上一次发言仍在处理，完成后自动恢复。'}}</div></div>
      <RegistrationPanel v-if="role==='chen' && session.registered" :registration="session.registration" :sid="session.id" :closed="session.closed" :locked="locked" @confirm="confirm" @draft="suggest"/>
      <div v-if="!session.closed" class="composer"><div v-if="failure" class="field-error" role="alert">{{failure}}</div><div v-if="role==='chen'" class="small-prompts"><button v-for="s in (session.registration.declined_all ? ['我想重新开始整个预登记。'] : session.registered ? ['登记资料用来做什么？','我停止整个预登记。'] : ['我对你介绍的岗位感兴趣。'])" :key="s" :disabled="locked" @click="suggest(s)">{{s}}</button></div><label class="sr-only" for="message">发给{{roleInfo.name}}的消息</label><textarea id="message" ref="input" v-model="text" maxlength="600" rows="3" :disabled="locked" :placeholder="`询问${roleInfo.name}…  请勿输入真实个人资料`" @keydown="enter"/><div class="composer-foot"><small>Enter 发送 · Shift + Enter 换行</small><button class="btn primary small" :disabled="!text.trim()||locked" @click="send">{{sending?'处理中':'发送'}}<SendHorizontal :size="15"/></button></div></div>
      <a v-else class="thread-return" :href="`#/review/${session.id}`"><ArrowLeft :size="15"/> 返回本场复盘</a>
    </section></div>
  <div v-if="!session.closed" class="decision-strip"><div><Flag :size="19"/><div><b>你准备好作判断了吗？</b><p>不必聊完所有人，也可以暂不作正式决定。</p></div></div><div class="decision-actions"><button class="text-btn" :disabled="locked" @click="closing='early'">提前结束训练</button><button class="btn primary" :disabled="locked" @click="closing='decision'">作出决策 <ArrowRight :size="15"/></button></div></div>
  <EndDialog v-if="closing" :kind="closing" :record="record" :session="session" @cancel="closing=null" @done="closing=null;emit('ended')"/>
</template>
