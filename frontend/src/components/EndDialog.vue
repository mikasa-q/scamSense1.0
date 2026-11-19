<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {ArrowRight, Flag, X} from 'lucide-vue-next'
import {finishSession} from '../api'
import {privateText,roles,type Choice,type RecordItem,type Session} from '../data'
const props=defineProps<{kind:'early'|'decision';record:RecordItem;session:Session}>()
const emit=defineEmits<{cancel:[];done:[]}>()
const dialog=ref<HTMLDialogElement>(); const selected=ref<Choice|null>(null), reason=ref(''), cited=ref<number[]>([]), busy=ref(false), error=ref('')
const choices:{key:Choice;label:string;desc:string}[]=[{key:'verify',label:'先核实再决定',desc:'暂缓推进，先寻找可独立核对的依据。'},{key:'continue',label:'继续了解机会',desc:'保留机会，继续走招聘流程。'},{key:'leave',label:'退出招聘流程',desc:'明确选择不再参与这次招聘。'}]
onMounted(()=>dialog.value?.showModal())
async function submit() {if(busy.value) return;error.value='';if(privateText(reason.value)) {error.value='判断理由中疑似含有真实个人资料，请改用虚构占位文字。'; return}busy.value=true
try {await finishSession(props.record,props.kind==='early'?{kind:'early'}:{kind:'decision',choice:selected.value!,reason:reason.value.trim(),cited:cited.value});emit('done')}
catch(e) {error.value=(e as Error).message}finally {busy.value=false}}
</script>
<template><dialog ref="dialog" class="decision-dialog" :aria-label="kind==='early'?'提前结束训练':'作出决策'" @cancel.prevent="!busy && emit('cancel')"><div class="dialog-top"><span class="eyebrow">CASE 001 &nbsp;/&nbsp; CHECKPOINT</span><button class="icon-button" aria-label="关闭" :disabled="busy" @click="emit('cancel')"><X :size="19"/></button></div><h2>{{kind==='early'?'提前结束本次训练？':'你的下一步是什么？'}}</h2><p>{{kind==='early'?'当前对话会被保存并生成复盘。这不代表你选择退出招聘，也不会生成一条正式决策。':'这是模拟中的正式选择。选择本身不代表对错，你可以用原话解释为什么。'}}</p>
  <form @submit.prevent="submit"><template v-if="kind==='decision'"><label v-for="c in choices" :key="c.key" :class="['choice',{picked:selected===c.key}]"><input type="radio" name="choice" :value="c.key" v-model="selected" required/><span><b>{{c.label}}</b><small>{{c.desc}}</small></span></label><label class="form-label" for="reason">判断理由 <small>选填</small></label><textarea id="reason" v-model="reason" rows="2" maxlength="600" placeholder="哪些说法影响了你的选择？请勿输入真实资料。"/><details v-if="session.messages.length" class="cite-list"><summary>引用本场原话（{{cited.length}} / 6）</summary><label v-for="m in session.messages" :key="m.id"><input type="checkbox" v-model="cited" :value="m.id" :disabled="cited.length>=6 && !cited.includes(m.id)"/><span><small>{{roles[m.role].name}}私聊 · {{m.speaker==='user'?'你':roles[m.role].name}}</small>{{m.body}}</span></label></details></template>
  <p v-if="error" class="field-error" role="alert">{{error}}</p><div class="dialog-actions"><button class="btn light" type="button" :disabled="busy" @click="emit('cancel')">返回私聊</button><button class="btn primary" type="submit" :disabled="busy || (kind==='decision' && !selected)">{{busy?'正在归档…':kind==='early'?'结束并查看复盘':'提交并查看复盘'}}<ArrowRight :size="15"/></button></div></form></dialog></template>
