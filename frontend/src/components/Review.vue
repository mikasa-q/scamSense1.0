<script setup lang="ts">
import {computed} from 'vue'
import {ArrowRight, CornerDownLeft} from 'lucide-vue-next'
import {roles, scene, statusText, submittedLabels, type FieldEntry, type Report, type RefQuote} from '../data'
const props=defineProps<{report:Report;sid:string}>()
const link=(ref:RefQuote)=>`#/chat/${props.sid}/${ref.role}?m=${ref.message_id}`
const chenLink=(id:number)=>`#/chat/${props.sid}/chen?m=${id}`
const fieldLabel=(key:string)=>props.report.registration?.items.find(i=>i.key===key)?.label
const turns=computed(()=>{
  const groups=new Map<number,FieldEntry[]>()
  for(const e of props.report.registration?.history ?? []) {
    if(!groups.has(e.message_id)) groups.set(e.message_id,[])
    groups.get(e.message_id)!.push(e)
  }
  return [...groups.values()]
})
</script>
<template><div class="page-intro"><div class="eyebrow"><span></span> FIELD NOTES &nbsp;/&nbsp; CASE 001</div><h1>本场训练复盘</h1><p>{{scene}} · 从原话出发，区分角色透露的信息和你自己的判断。</p></div><div class="report-summary"><div class="eyebrow">SESSION OUTCOME</div><h2>{{report.ending.label}}</h2><p>{{report.ending.kind==='early'?'你结束了模拟，没有作正式招聘决定。':report.ending.reason ? `你的判断理由：「${report.ending.reason}」` : '你提交了正式选择，没有填写判断理由。'}}</p><small>综合分：{{report.total??'—'}} &nbsp; / &nbsp; 量表未定稿，不按缺失项重算总分。</small></div>
  <section v-if="report.registration" class="desk-section" aria-label="登记复盘"><header class="section-head"><h2>你实际提交了什么</h2></header>
    <div class="panel clues"><h3>已提交项：{{submittedLabels(report.registration)}}</h3><p class="muted">这里只统计实际发给陈浩的虚构占位资料。表达同意和选择终局都不算提交。</p>
      <ul class="field-list"><li v-for="i in report.registration.items" :key="i.key"><b>{{i.label}}</b> · {{i.status ? statusText[i.status] : '未表态'}}</li></ul>
      <article v-for="e in report.registration.references" :key="e.message_id" class="ref-entry"><small>{{e.speaker==='user'?'你':'陈浩'}} · 登记对话</small><blockquote>{{e.quote}}</blockquote><a :href="link(e)">定位原话 <CornerDownLeft :size="13"/></a></article>
      <article v-for="turn in turns" :key="turn[0].message_id" class="ref-entry">
        <div v-for="e in turn" :key="e.field"><small>你 · {{fieldLabel(e.field)}} · {{statusText[e.status]}}</small><blockquote>{{e.quote}}</blockquote></div>
        <a :href="chenLink(turn[0].message_id)">定位你的原话 <CornerDownLeft :size="13"/></a>
        <p>陈浩当时的回复</p><blockquote>{{turn[0].reply_quote}}</blockquote><a :href="chenLink(turn[0].reply_id)">定位陈浩原话 <CornerDownLeft :size="13"/></a>
      </article>
    </div>
  </section>
  <section class="desk-section"><header class="section-head"><div><div class="eyebrow">01 &nbsp;/&nbsp; BEHAVIOR</div><h2>你的行为证据</h2></div></header><div class="dimension-grid"><article v-for="d in report.dimensions" :key="d.key" class="dimension panel"><div class="dimension-title"><h3>{{d.label}}</h3><span>{{d.weight}}%</span></div><p class="dim-status">{{d.score!==null?d.score+' 分':d.status==='insufficient'?'证据不足':'已找到依据 · 待定标'}}</p><div v-for="(e,i) in d.evidence" :key="i" class="ref-entry"><small>{{roles[e.role].name}}私聊 · {{e.speaker==='user'?'你':roles[e.role].name}}</small><blockquote>{{e.quote}}</blockquote><p>{{e.why}}</p><a :href="link(e)">定位原话 <CornerDownLeft :size="13"/></a></div><p v-if="!d.evidence.length" class="muted">没有足够原文支持这一维度，不记为 0 分。</p></article></div></section>
  <section class="desk-section"><header class="section-head"><div><div class="eyebrow">02 &nbsp;/&nbsp; DISCLOSURES</div><h2>角色实际透露了什么</h2></div></header><div class="panel clues"><p class="muted" v-if="!report.disclosures.length">本场没有可引用的角色线索。获准谈论某件事，不代表角色已经说出。</p><article v-for="(e,i) in report.disclosures" :key="i" class="ref-entry"><small>{{e.focus}} / {{e.topic}} · {{roles[e.role].name}}</small><blockquote>{{e.quote}}</blockquote><p>{{e.why}}</p><a :href="link(e)">定位原话 <CornerDownLeft :size="13"/></a></article></div></section>
  <section v-if="report.follow_ups" class="desk-section"><header class="section-head"><h2>还有什么值得核实</h2></header><div class="panel clues"><ul class="follow-ups"><li v-for="f in report.follow_ups" :key="f.focus"><b>{{f.topic}}</b> · {{f.question}}<small>{{f.basis}}</small></li></ul></div></section>
  <div class="report-end"><a :href="`#/chat/${sid}/wang`" class="btn light">回看全部私聊</a><a href="#/desk" class="btn primary">回到工作台 <ArrowRight :size="15"/></a></div></template>
