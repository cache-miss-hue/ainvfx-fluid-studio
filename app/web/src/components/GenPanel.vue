<script setup>
import { computed } from 'vue'
import { S, genActive, cancelGenerate, dismissJob } from '../store'

const job = computed(() => S.genJob)
const pct = computed(() => Math.round((job.value ? job.value.progress || 0 : 0) * 100))
const stateText = computed(() => {
  const j = job.value
  if (!j) return ''
  if (j.state === 'queued') return '排队中'
  if (j.state === 'running') return j.stage || '生成中'
  return { done: '已完成', error: '生成失败', cancelled: '已取消' }[j.state] || j.state
})
</script>

<template>
  <div v-if="job" class="gp" :class="job.state">
    <div class="row">
      <b class="grow">{{ stateText }}<span v-if="job.step && job.state === 'running'"> · 采样 {{ job.step }}</span></b>
      <span class="dim" v-if="genActive">{{ pct }}%</span>
      <button v-if="genActive" class="small danger" @click="cancelGenerate">取消</button>
      <button v-else class="small" @click="dismissJob">关闭</button>
    </div>
    <div class="bar" v-if="genActive"><i :style="{ width: pct + '%' }"></i></div>
    <div v-if="job.message && genActive" class="msg">{{ job.message }}</div>
    <div v-if="job.state === 'error'" class="errm">{{ job.error || '生成失败，请重试' }}</div>
    <ul v-if="job.notes && job.notes.length" class="notes">
      <li v-for="(n, i) in job.notes" :key="i">{{ n }}</li>
    </ul>
  </div>
</template>

<style scoped>
.gp { position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%); width: min(620px, 92%); background: rgba(28, 31, 37, .96);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; box-shadow: 0 8px 30px rgba(0,0,0,.6); z-index: 30; display: flex; flex-direction: column; gap: 6px; }
.gp.error { border-color: var(--err); }
.gp.done { border-color: var(--ok); }
.bar { height: 8px; background: #0e1013; border-radius: 4px; overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width .3s; }
.msg { color: var(--warn); font-size: 12px; }
.errm { color: #ffb3b3; background: #4a1c1c; border-radius: 5px; padding: 6px 9px; }
.notes { margin: 0; padding-left: 18px; color: var(--dim); font-size: 12px; }
</style>
