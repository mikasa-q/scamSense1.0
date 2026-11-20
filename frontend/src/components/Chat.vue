<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {ArrowLeft, ArrowRight, BookOpenText, ChevronRight, CircleAlert, Flag, LockKeyhole, MessageCircle, RefreshCw, SendHorizontal, ShieldCheck} from 'lucide-vue-next'
import {keys, roles, scene, stages, timeText, privateText, type Role, type Session, type RecordItem} from '../data'
import {sendTurn} from '../api'
import Portrait from './Portrait.vue'
import EndDialog from './EndDialog.vue'
import RegistrationPanel from './RegistrationPanel.vue'
const props=defineProps<{session:Session; record:RecordItem; role:Role; target:number; configured:boolean|null}>()
const emit=defineEmits<{saved:[s:Session]; reload:[]; check:[]; ended:[]}>()
const visibleMessages=computed(()=>props.session.messages.filter(m=>m.role===props.role))
const roleInfo=computed(()=>roles[props.role]); const text=ref(''), progress=ref(''), failure=ref(''), sending=ref(false)
const lastRequest=ref<{key:string;id:string}|null>(null); const pendingText=ref(''); const input=ref<HTMLTextAreaElement>(); const scroll=ref<HTMLDivElement>()
const closing=ref<'early'|'decision'|null>(null)
const locked=computed(()=>sending.value || props.session.busy)
const poll=window.setInterval(()=>{if(props.session.busy && !sending.value) emit('reload')},2500)
onBeforeUnmount(()=>window.clearInterval(poll))
const threadLink=(role:Role)=>`#/chat/${props.session.id}/${role}`
async function position() {await nextTick(); const target=props.target && document.getElementById(`msg-${props.target}`); if(target) target.scrollIntoView({block:'nearest'}); else if(scroll.value) scroll.value.scrollTop=scroll.value.scrollHeight}
onMounted(position)
watch(()=>[props.role, props.target],()=>{text.value=''; failure.value=''; lastRequest.value=null; position()})
watch(()=>[visibleMessages.value.length,progress.value],position)
function suggest(v:string) {text.value=v; input.value?.focus()}
function addChoice(v:string) {suggest([text.value.trim(),v].filter(Boolean).join('，'))}
async function send() {
  const body=text.value.trim(); if(!body || locked.value || props.session.closed) return
  if(privateText(body)) { failure.value='请移除疑似真实的个人资料，改用「虚构资料 A」等占位文字。'; return }
  const key=props.role+'\0'+body; const rid=lastRequest.value?.key===key?lastRequest.value.id:crypto.randomUUID()
  lastRequest.value={key,id:rid}; sending.value=true; failure.value=''; progress.value='正在连接训练服务'; pendingText.value=body
  try {const s=await sendTurn(props.record,props.role,body,rid,v=>progress.value=v); emit('saved',s); text.value=''; lastRequest.value=null}
  catch(e) {failure.value=(e as Error).message; emit('reload'); emit('check')}
  finally {sending.value=false;progress.value='';pendingText.value=''; await nextTick();input.value?.focus()}
}
function enter(e:KeyboardEvent) {if(e.key==='Enter' && !e.isComposing && !e.shiftKey && e.keyCode!==229) {e.preventDefault();send()}}
</script>
<template>
  <div class="page-intro compact"><div class="eyebrow"><span></span> PRIVATE CHANNELS &nbsp;/&nbsp; CASE 001</div><div class="title-line"><h1>{{scene}}</h1><span class="stage-pill">S{{session.stage}} · {{stages[session.stage]}}</span></div><p>每位联系人只能看到与你的私聊。用户转述不等于独立核实。</p></div>
  <div v-if="configured===false && !session.closed" class="notice"><CircleAlert :size="18"/><div><b>尚未配置对话模型</b><p>可以浏览训练空间；真实私聊需在后端配置 OpenAI 兼容服务。<a href="#/sample">先看只读示例</a></p></div><button class="icon-button" title="重新检查模型配置" aria-label="重新检查模型配置" @click="emit('check')"><RefreshCw :size="16"/></button></div>
  <details class="case-brief panel" :open="!session.messages.length"><summary>开场线索 · 两份 Python 实习介绍</summary>
    <div class="opening-grid"><article v-for="o in session.openings" :key="o.role"><small>{{roles[o.role].name}} · {{roles[o.role].job}}</small><h3>{{o.title}}</h3><p>{{o.description}}</p><p><b>消息来源：</b>{{o.source}}</p></article></div>
    <p class="muted">两份介绍不是相互背书。可以先找任意一位联系人核实，不需要先登记。</p>
  </details>
  <div class="chat-layout"><aside class="roster panel"><div class="panel-label">联系人 <span>03</span></div><a v-for="k in keys" :key="k" :href="threadLink(k)" :class="['roster-row',{selected:k===role}]" :aria-current="k===role?'page':undefined" @click="sending && $event.preventDefault()"><Portrait :role="k"/><span><b>{{roles[k].name}}</b><small>{{roles[k].job}}</small></span><ChevronRight :size="15"/></a><div class="roster-foot"><LockKeyhole :size="14"/> 三个独立对话空间</div></aside>
    <section class="thread panel"><div class="thread-head"><Portrait :role="role"/><div><b>{{roleInfo.name}}</b><small>{{roleInfo.job}} · 虚构联系人</small></div><span class="neutral-pill">{{ session.closed?'只读回看':'私聊' }}</span></div>
      <div ref="scroll" class="thread-scroll" role="log" aria-label="私聊记录" aria-live="polite"><div v-if="!visibleMessages.length" class="empty-thread"><span class="empty-icon"><MessageCircle :size="24"/></span><h3>与{{roleInfo.name}}的私聊</h3><p>{{roleInfo.intro}}</p><button v-if="!session.closed" class="prompt-chip" :disabled="locked" @click="suggest(roleInfo.ask)">试着问：{{roleInfo.ask}} <ArrowRight :size="13"/></button></div>
        <div v-for="m in visibleMessages" :id="`msg-${m.id}`" :key="m.id" :class="['message',m.speaker,{highlight:target===m.id}]" tabindex="-1"><small>{{m.speaker==='user'?'你':roleInfo.name}} · {{timeText(m.created)}} <span v-if="target===m.id"> / 复盘引文所在消息</span></small><p>{{m.body}}</p></div>
        <div v-if="sending" class="message user draft-bubble"><small>你 · 待校验，尚未写入</small><p>{{pendingText}}</p></div><div v-if="locked" class="working"><i></i>{{progress || '上一次发言仍在处理，完成后自动恢复。'}}</div></div>
      <RegistrationPanel v-if="role==='chen' && session.registered" :registration="session.registration" :sid="session.id" :closed="session.closed" :locked="locked" @draft="addChoice"/>
      <div v-if="!session.closed" class="composer"><div v-if="failure" class="field-error" role="alert">{{failure}}</div><div v-if="role==='chen'" class="small-prompts"><button v-for="s in (session.registered ? ['登记资料用来做什么？','我不参与预登记。'] : ['我对你介绍的 Python 实习感兴趣。'])" :key="s" :disabled="locked" @click="suggest(s)">{{s}}</button></div><label class="sr-only" for="message">发给{{roleInfo.name}}的消息</label><textarea id="message" ref="input" v-model="text" maxlength="600" rows="3" :disabled="locked" :placeholder="`询问${roleInfo.name}…  请勿输入真实个人资料`" @keydown="enter"/><div class="composer-foot"><small>Enter 发送 · Shift + Enter 换行</small><button class="btn primary small" :disabled="!text.trim()||locked" @click="send">{{sending?'处理中':'发送'}}<SendHorizontal :size="15"/></button></div></div>
      <a v-else class="thread-return" :href="`#/review/${session.id}`"><ArrowLeft :size="15"/> 返回本场复盘</a>
    </section></div>
  <div v-if="!session.closed" class="decision-strip"><div><Flag :size="19"/><div><b>你准备好作判断了吗？</b><p>不必聊完所有人，也可以暂不作正式决定。</p></div></div><div class="decision-actions"><button class="text-btn" :disabled="locked" @click="closing='early'">提前结束训练</button><button class="btn primary" :disabled="locked" @click="closing='decision'">作出决策 <ArrowRight :size="15"/></button></div></div>
  <EndDialog v-if="closing" :kind="closing" :record="record" :session="session" @cancel="closing=null" @done="closing=null;emit('ended')"/>
</template>
