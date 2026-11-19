<script setup lang="ts">
import {ArrowRight, ArrowUpRight, BookOpenText, CheckCheck, Clock3, Compass, FileSearch, FolderOpen, ListChecks, MessageCircle, MessagesSquare, ScanLine, UsersRound} from 'lucide-vue-next'
import {keys, roles, scene, type Role} from '../data'
import CaseArt from './CaseArt.vue'
import Portrait from './Portrait.vue'
defineProps<{resume:boolean; starting:boolean}>()
const emit=defineEmits<{start:[role?:Role]}>()
const steps=[{title:'分别私聊',text:'选择联系人，自由提问',icon:MessagesSquare},{title:'核对信息',text:'追问来源，比较说法',icon:FileSearch},{title:'作出决定',text:'选择下一步并说明理由',icon:ListChecks},{title:'回到原话',text:'沿证据回看自己的判断',icon:BookOpenText}]
</script>
<template>
  <div class="page-intro"><div class="eyebrow"><span></span> TRAINING DESK</div><h1>训练工作台</h1><p>在虚构的求职现场，练习提问、核实与判断。</p></div>
  <section class="case-banner" aria-labelledby="case-title"><div class="banner-content"><div class="banner-meta"><span class="live-tag"><i></i> 情境训练</span><span>CASE FILE &nbsp; / &nbsp; 001</span></div><h2 id="case-title">{{scene}}</h2><p>一条校园群转发，三位与你联系的人。<br>在提交资料之前，你想先弄清楚什么？</p><div class="banner-actions"><button class="btn acid" :disabled="starting" @click="emit('start')">{{starting?'正在进入…':resume?'继续训练':'进入训练'}}<ArrowRight :size="17"/></button><a href="#/sample" class="banner-link"><BookOpenText :size="16"/> 查看示例复盘 <ArrowUpRight :size="13"/></a></div></div><CaseArt/><span class="banner-folio">SS—FIELD LAB &nbsp; / &nbsp; VOL. 01</span></section>
  <div class="micro-row"><span><UsersRound/>3 位联系人</span><i></i><span><MessageCircle/>独立私聊</span><i></i><span><Clock3/>不限时</span></div>
  <section class="desk-section"><header class="section-head"><div><div class="eyebrow">01 &nbsp;/&nbsp; CONTACTS</div><h2>本场联系人</h2></div><small>选一位，开始了解情况</small></header><div class="contact-grid"><button v-for="k in keys" :key="k" class="contact-card" :disabled="starting" @click="emit('start', k)"><span class="contact-top"><Portrait :role="k"/><span class="person-meta"><b>{{roles[k].name}}</b><small>{{roles[k].job}}</small></span><span class="round-arrow"><ArrowUpRight :size="15"/></span></span><span class="card-desc">{{roles[k].intro}}</span></button></div></section>
  <section class="desk-section"><header class="section-head"><div><div class="eyebrow">02 &nbsp;/&nbsp; FIELD GUIDE</div><h2>一次训练怎么进行</h2></div><a href="#/guide" class="text-link">训练指南 <ArrowRight :size="14"/></a></header><div class="steps"><div v-for="(s,i) in steps" :key="s.title" class="step"><span class="step-icon"><component :is="s.icon" :size="19"/></span><div><small>STEP 0{{i+1}}</small><b>{{s.title}}</b><p>{{s.text}}</p></div></div></div></section>
</template>
