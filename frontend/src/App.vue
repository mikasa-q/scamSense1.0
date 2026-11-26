<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {ArrowLeft, ArrowRight, ArrowUpRight, BookOpenText, Check, ChevronRight, CircleHelp, Fingerprint, FolderClock, LayoutDashboard, LockKeyhole, Menu, MessageSquareText, NotebookPen, PanelLeft, Plus, Radio, RefreshCw, ShieldCheck, X} from 'lucide-vue-next'
import Desk from './components/Desk.vue'
import Chat from './components/Chat.vue'
import Review from './components/Review.vue'
import {captureInvitation,createSession,getSession,health} from './api'
import {dateText,keys,scene,stages,type RecordItem,type Role,type Session} from './data'
const titles={desk:'训练工作台',archive:'训练记录',sample:'示例复盘',guide:'训练指南',chat:'角色私聊',review:'训练复盘'} as const
type Page=keyof typeof titles
function route() {
  const [path,query]=location.hash.slice(1).split('?');const [p,id,role]=(path||'/desk').split('/').filter(Boolean)
  return {page:(p && Object.hasOwn(titles,p)?p:'desk') as Page,id:id||'',role:keys.includes(role as Role)?role as Role:'wang' as Role,target:Number(new URLSearchParams(query).get('m')||0)}
}
const invited=ref(captureInvitation()), classroom=ref(false)
const r=ref(route()), menu=ref(false), error=ref(''),loading=ref(false),starting=ref(false), config=ref<boolean|null>(null), session=ref<Session|null>(null)
const storage='scamsense.archive.v1'
function savedRecords():RecordItem[] {try {const value=JSON.parse(localStorage.getItem(storage)||'[]');return Array.isArray(value)?value.filter(x=>typeof x.id==='string'&&typeof x.token==='string'&&typeof x.created==='string'):[]}catch{return []}}
const records=ref(savedRecords()); const latest=computed(()=>records.value.find(v=>!v.closed));const current=computed(()=>records.value.find(v=>v.id===r.value.id))
watch(records,v=>{try{localStorage.setItem(storage,JSON.stringify(v))}catch{error.value='浏览器未允许保存凭据。离开此页面后可能无法恢复本场训练。'}},{deep:true,flush:'sync'})
function accept(s:Session) {const item=records.value.find(v=>v.id===s.id);if(item) Object.assign(item,{closed:s.closed,stage:s.stage,count:s.messages.length}); if(r.value.id===s.id)session.value=s}
let loadSeq=0
async function load(quiet=false) {const id=r.value.id,seq=++loadSeq;if(!quiet)error.value='';if(!['chat','review'].includes(r.value.page)){session.value=null;loading.value=false;return}
  if(!current.value){session.value=null;loading.value=false;error.value='当前浏览器没有这场训练的访问凭据。请返回工作台开始新训练。';return}
  if(session.value?.id!==id)session.value=null;if(!quiet)loading.value=!session.value
  try {const s=await getSession(current.value);if(seq===loadSeq&&r.value.id===id){accept(s);if(r.value.page==='review'&&!s.closed)location.replace(`#/chat/${id}/wang`)}}
  catch(e) {if(seq===loadSeq)error.value=(e as Error).message}finally{if(seq===loadSeq)loading.value=false}}
async function check(){try{const h=await health();config.value=h.model_configured;classroom.value=h.invite_required}catch{config.value=null}}
async function start(role:Role='wang',force=false) {if(starting.value)return;starting.value=true;error.value='';try {let item=force?undefined:latest.value;if(!item){const s=await createSession();item={...s,closed:false,count:0,stage:0};records.value.unshift(item)}location.hash=`/chat/${item.id}/${role}`}catch(e){error.value=(e as Error).message}finally{starting.value=false}}
function routeChange(){invited.value=captureInvitation();const old=r.value;r.value=route();menu.value=false;error.value='';document.title=`${titles[r.value.page]} · ScamSense`;if(r.value.page!==old.page || r.value.id!==old.id){window.scrollTo(0,0);load()}if(r.value.page==='chat')check()}
function stored(e:StorageEvent){if(e.key===storage){records.value=savedRecords();if(!current.value&&['chat','review'].includes(r.value.page))load()}}
function documentFocus(){document.getElementById('main-content')?.focus()}
function locationToReview(){location.hash=`/review/${r.value.id}`}
function esc(e:KeyboardEvent){if(e.key==='Escape')menu.value=false}
const sampleHeight=ref(730);let observer:ResizeObserver|undefined
function fitSample(e:Event) {observer?.disconnect();const el=(e.target as HTMLIFrameElement).contentDocument?.body;if(!el)return;const fit=()=>{sampleHeight.value=Math.ceil(el.getBoundingClientRect().height)+4};observer=new ResizeObserver(fit);observer.observe(el);fit()}
onMounted(()=>{window.addEventListener('hashchange',routeChange);window.addEventListener('storage',stored);window.addEventListener('keydown',esc);document.title=`${titles[r.value.page]} · ScamSense`;load();check()})
onBeforeUnmount(()=>{window.removeEventListener('hashchange',routeChange);window.removeEventListener('storage',stored);window.removeEventListener('keydown',esc);observer?.disconnect()})
const nav=[{page:'desk',label:'训练工作台',icon:LayoutDashboard},{page:'archive',label:'训练记录',icon:FolderClock},{page:'sample',label:'示例复盘',icon:NotebookPen}]
const guides=[{q:'这是用来判断真实招聘方的吗？',a:'不是。ScamSense 是一个虚构的练习场，不对现实企业、岗位或联系人给出真假结论。你要练习的是提出问题、比较来源，并说明自己为什么这样决定。'},{q:'为什么联系人看不到另一段聊天？',a:'三段私聊彼此独立。你可以转述别人的话，但转述仍然只有一个来源，不会自动成为独立背书。'},{q:'哪些内容可以输入？',a:'只输入训练用的虚构文字，例如「虚构资料 A」。不要提供真实证件、住址、电话或账户。系统会拦截常见的疑似敏感格式，但不能替你识别所有个人信息。通过检查的对话内容将送往后端配置的模型服务。'},{q:'提前结束和退出招聘流程有什么不同？',a:'提前结束只结束练习，不记录正式招聘决策。退出招聘流程是正式选择之一，可以附上理由和原文依据；任何选择本身都不自动得分。'},{q:'为什么没有总分？',a:'复盘只采纳经核对的用户证据。没有有效原文就显示「证据不足」，不按零分处理。当前评分档位和阈值尚未确认，因此即使找到证据也不显示数值分。'},{q:'如何继续上一次训练？',a:'使用同一浏览器打开训练记录，选择进行中的训练。聊天记录在后端保存，访问凭据只存在此浏览器，不在页面地址中。清除浏览器数据会丢失访问凭据。'}]
</script>
<template><a class="skip-link" href="#main-content" @click.prevent="documentFocus">跳至主要内容</a><div class="app-shell">
  <div v-if="menu" class="nav-overlay" @click="menu=false"></div><aside :class="['sidebar',{open:menu}]" aria-label="主导航"><a href="#/desk" class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><rect x="1" y="1" width="38" height="38" rx="11" fill="#214439"/><g fill="none" stroke="#def098" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18v-6h6m10 0h6v6m0 6v5h-6M9 24v5h6"/><path d="M25 16h-8a2.5 2.5 0 0 0 0 5h5a2.5 2.5 0 0 1 0 5h-8" transform="translate(0 -1)"/></g></svg><span>ScamSense<small>求职判断力训练室</small></span></a><button class="mobile-close icon-button" aria-label="收起导航" @click="menu=false"><X :size="20"/></button>
  <div class="nav-caption">WORKSPACE <i></i></div><nav><a v-for="n in nav" :key="n.page" :href="`#/${n.page}`" :class="{active:r.page===n.page || (n.page==='desk'&&r.page==='chat') || (n.page==='archive'&&r.page==='review')}" :aria-current="r.page===n.page?'page':undefined"><component :is="n.icon" :size="18"/>{{n.label}}</a></nav><div class="nav-caption second">RESOURCES <i></i></div><nav><a href="#/guide" :class="{active:r.page==='guide'}"><CircleHelp :size="18"/>训练指南</a></nav><div class="sidebar-end"><div class="privacy-symbol"><ShieldCheck :size="20"/></div><span><b>虚构情境训练</b><small>不使用真实个人资料</small></span></div></aside>
  <div class="workspace"><header class="topbar"><div><button class="mobile-menu icon-button" aria-label="展开导航" :aria-expanded="menu" @click="menu=true"><Menu :size="20"/></button><PanelLeft class="desktop-mark" :size="16"/><span class="crumb">训练空间</span><ChevronRight :size="13"/><b>{{titles[r.page]}}</b></div><span class="lab-status"><i></i> FIELD LAB <span>/</span> 校园版</span></header>
  <main id="main-content" tabindex="-1"><div v-if="error" class="notice global-error" role="alert"><div><b>暂时无法完成操作</b><p>{{error}}</p></div><button v-if="current" class="icon-button" aria-label="重试加载" @click="load()"><RefreshCw :size="16"/></button><button class="icon-button" aria-label="关闭提示" @click="error='' "><X :size="16"/></button></div>
    <div v-if="classroom && r.page==='desk'" class="notice" role="status"><ShieldCheck :size="18"/><div><b>班级训练</b><p>{{invited?'已读取邀请。点击下方按钮进入自己的训练。':'新建训练请使用组织者发给你的班级邀请链接；已有训练仍可从训练记录进入。'}}</p><p>你的对话会交给模型服务处理，请只使用虚构资料。</p></div></div>
    <Desk v-if="r.page==='desk'" :resume="!!latest" :starting="starting" @start="start"/>
    <template v-else-if="r.page==='archive'"><div class="page-intro"><div class="eyebrow"><span></span> SESSION ARCHIVE</div><div class="title-line"><h1>训练记录</h1><button class="btn primary small" :disabled="starting" @click="start('wang',true)"><Plus :size="16"/>新建训练</button></div><p>继续未结束的练习，或回看已归档的判断依据。仅列出本浏览器的训练。</p></div><div v-if="!records.length" class="panel empty-state"><span class="empty-icon"><FolderClock :size="28"/></span><h2>还没有训练记录</h2><p>从一条校园群招聘消息开始，完成的对话会保存在这里。</p><button class="btn primary" :disabled="starting" @click="start()">开始第一场训练 <ArrowRight :size="16"/></button></div><div v-else class="archive-list"><a v-for="item in records" :key="item.id" :href="`#/${item.closed?'review':'chat'}/${item.id}${item.closed?'':'/wang'}`" class="archive-row panel"><span class="archive-icon"><FolderClock :size="21"/></span><span class="archive-info"><b>{{scene}}</b><small>{{dateText(item.created)}} · {{item.count}} 条消息</small></span><span class="stage-pill">{{item.closed?'已归档':stages[item.stage]}}</span><ChevronRight :size="16"/></a></div></template>
    <template v-else-if="r.page==='sample'"><iframe title="只读示例：核实转发消息的来源" class="sample-frame" src="./fieldnote.html?embed=1" :style="{height:sampleHeight+'px'}" @load="fitSample"></iframe></template>
    <template v-else-if="r.page==='guide'"><div class="page-intro"><div class="eyebrow"><span></span> USER HANDBOOK</div><h1>训练指南</h1><p>先知道什么会留下证据，再开始自由提问。</p></div><div class="guide-lead"><ShieldCheck :size="29"/><div><b>不是猜谁在说谎，而是找到判断的依据。</b><p>角色说过什么、你问过什么，以及你得出了什么结论，是三件不同的事。</p></div></div><details v-for="(g,i) in guides" :key="g.q" class="guide-item" :open="i===0"><summary>{{g.q}}<Plus :size="16"/></summary><p>{{g.a}}</p></details><div class="report-end"><a href="#/sample" class="btn light">看一份示例复盘</a><a href="#/desk" class="btn primary">回到工作台 <ArrowRight :size="16"/></a></div></template>
    <div v-else-if="loading" class="panel empty-state" role="status">正在打开本场训练…</div>
    <Chat v-else-if="r.page==='chat'&&session&&current" :key="session.id" :session="session" :record="current" :role="r.role" :target="r.target" :configured="config" :reload="() => load(true)" @saved="accept" @check="check" @ended="locationToReview"/>
    <Review v-else-if="r.page==='review'&&session?.review" :report="session.review" :sid="session.id" :messages="session.messages"/>
    <a v-else href="#/desk" class="btn light"><ArrowLeft :size="15"/> 回到工作台</a>
    <footer class="page-foot"><span>SCAMSENSE &nbsp; / &nbsp; FIELD LAB</span><span>仅供模拟训练 · 不鉴定真实招聘方</span></footer></main></div></div></template>
