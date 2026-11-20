<script setup lang="ts">
import {statusText, submittedLabels, type FieldItem, type FieldStatus, type Registration} from '../data'

defineProps<{registration:Registration; sid:string; locked:boolean; closed:boolean}>()
const emit = defineEmits<{draft:[text:string]}>()
function wording(item:FieldItem, status:FieldStatus) {
  const field = item.label
  return {agreed:`${field}可以给`, submitted:`我提交的${field}：${item.placeholder}`, deferred:`${field}先不提供`, refused:`我拒绝提供${field}`}[status]
}
</script>
<template>
  <section class="registration-panel" aria-label="候选人预登记">
    <div class="dimension-title"><h3>候选人预登记</h3><span class="neutral-pill">仅限虚构资料</span></div>
    <p v-if="registration.declined_all" class="muted">你已停止整个登记。之前的记录仍保留，可以继续问岗位问题。</p>
    <p v-else class="muted">可以分别表态，也可以继续提问。同意不等于提交；只有发出对应的虚构占位值才算提交。</p>
    <ul class="field-list">
      <li v-for="item in registration.items" :key="item.key">
        <div><b>{{item.label}}</b> <span class="stage-pill">{{item.status ? statusText[item.status] : '未表态'}}</span></div>
        <a v-if="item.message_id" :href="`#/chat/${sid}/chen?m=${item.message_id}`">你的原话：「{{item.quote}}」</a>
        <details v-if="!closed && !registration.declined_all"><summary>拟写{{item.label}}的回应</summary>
          <p>虚构占位值：{{item.placeholder}}。点选只写入草稿，不会发送。</p>
          <div class="small-prompts"><button v-for="(label, status) in statusText" :key="status" type="button" :disabled="locked" @click="emit('draft',wording(item,status))">{{status==='submitted' ? '提交虚构占位值' : label}}</button></div>
        </details>
      </li>
    </ul>
    <p><b>已提交项：</b>{{submittedLabels(registration)}}</p>
    <div v-for="entry in registration.history.filter(e=>e.status==='submitted')" :key="`${entry.message_id}-${entry.field}-${entry.position}`" class="submission-ref"><a :href="`#/chat/${sid}/chen?m=${entry.message_id}`">提交原话：「{{entry.quote}}」</a></div>
  </section>
</template>
<style scoped>
.registration-panel{padding:14px 18px;border-top:1px solid var(--line);background:#f5f8ef}
.registration-panel p,.registration-panel a,.registration-panel summary{font-size:13px;line-height:1.7}
.field-list{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr));gap:12px;margin:12px 0}
.field-list li{padding-left:12px;border-left:3px solid #c4d5b3;min-width:0}.registration-panel a{display:block;text-decoration:underline;overflow-wrap:anywhere}.field-list summary{cursor:pointer}.field-list details{margin-top:6px}
</style>
