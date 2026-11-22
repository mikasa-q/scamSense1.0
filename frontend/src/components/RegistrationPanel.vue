<script setup lang="ts">
import {dateText, statusText, submittedLabels, type OptionId, type Registration} from '../data'

defineProps<{registration:Registration; sid:string; locked:boolean; closed:boolean}>()
const emit = defineEmits<{confirm:[option:OptionId]; draft:[text:string]}>()
const choices = {agreed:'可以给', deferred:'先不提供', refused:'不愿提供'} as const
</script>
<template>
  <section class="registration-panel" aria-label="候选人预登记">
    <div class="dimension-title"><h3>候选人预登记</h3><span class="neutral-pill">仅限虚构资料</span></div>
    <p v-if="closed" class="muted">训练已结束，以下为本场记录。</p>
    <p v-else-if="registration.declined_all" class="muted">你已停止整个登记，不能提交。可以继续聊天，也可以明确告诉陈浩要重新开始登记。</p>
    <p v-else-if="registration.scope_pending" class="muted">旧会话的拒绝范围尚待确认，暂不能提交；可以继续聊天。</p>
    <p v-else class="muted">登记已开放。聊天只表达意愿；点下方按钮才会提交对应的虚构资料，不会发送聊天消息。</p>
    <ul class="field-list">
      <li v-for="item in registration.items" :key="item.key">
        <div><b>{{item.label}}</b> <span class="stage-pill">{{registration.submitted.includes(item.key) ? '已提交' : '未提交'}}</span></div>
        <small>最近聊天表态：{{item.status ? statusText[item.status] : '未表态'}}</small>
        <a v-if="item.message_id" :href="`#/chat/${sid}/chen?m=${item.message_id}`">你的原话：「{{item.quote}}」</a>
        <button v-if="!closed && !registration.declined_all && !registration.scope_pending" class="btn primary small" type="button" :disabled="locked || registration.submitted.includes(item.key)" @click="emit('confirm',item.option_id)">提交{{item.placeholder}}</button>
        <details v-if="!closed && !registration.declined_all"><summary>拟写{{item.label}}的聊天表态</summary>
          <small>只写入草稿，不会发送或提交资料。</small>
          <div class="small-prompts"><button v-for="(phrase,status) in choices" :key="status" type="button" :disabled="locked" @click="emit('draft',item.label+phrase)">{{statusText[status]}}</button></div>
        </details>
      </li>
    </ul>
    <p><b>已提交项：</b>{{submittedLabels(registration)}}</p>
    <div v-for="(entry,i) in registration.history.filter(e=>e.status==='submitted')" :key="i" class="submission-ref">
      <span v-if="entry.source==='explicit'">显式确认 · {{entry.value}} · {{dateText(entry.created)}}</span>
      <a v-else :href="`#/chat/${sid}/chen?m=${entry.message_id}`">旧版聊天提交：「{{entry.quote}}」</a>
    </div>
  </section>
</template>
<style scoped>
.registration-panel{padding:14px 18px;border-top:1px solid var(--line);background:#f5f8ef}
.registration-panel p,.registration-panel a,.submission-ref{font-size:13px;line-height:1.7}
.field-list{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr));gap:12px;margin:12px 0}
.field-list li{display:grid;align-content:start;justify-items:start;gap:5px;padding-left:12px;border-left:3px solid #c4d5b3;min-width:0}.registration-panel a{text-decoration:underline;overflow-wrap:anywhere}
</style>
