<script setup>
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { S } from '../store'
import GlossaryModal from './GlossaryModal.vue'
import ProjectList from './ProjectList.vue'
import TranslateSettings from './TranslateSettings.vue'

const inp = ref(null)
const val = ref('')
watch(() => S.dialog, async (d) => {
  if (d && d.kind === 'input') { val.value = d.value || ''; await nextTick(); inp.value && inp.value.focus(); inp.value && inp.value.select() }
})
function close(ok) {
  const d = S.dialog
  S.dialog = null
  if (!d) return
  if (d.kind === 'input') d.resolve(ok ? val.value : null)
  else d.resolve(d.check ? { ok, checked: !!d.checked } : ok)
}
// 确认框：Enter = 确定，Esc = 取消（输入框自己处理）
function onKey(e) {
  if (!S.dialog || S.dialog.kind !== 'confirm') return
  if (e.key === 'Escape') { e.preventDefault(); close(false) }
  else if (e.key === 'Enter') { e.preventDefault(); close(true) }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div v-if="S.dialog" class="mask" @mousedown.self="close(false)">
    <div class="box">
      <h3>{{ S.dialog.title }}</h3>
      <p v-if="S.dialog.message" class="msg">{{ S.dialog.message }}</p>
      <input v-if="S.dialog.kind === 'input'" ref="inp" type="text" v-model="val" @keydown.enter="close(true)" @keydown.esc="close(false)" style="width:100%" />
      <label v-if="S.dialog.check" class="row chk"><input type="checkbox" v-model="S.dialog.checked" /> {{ S.dialog.check }}</label>
      <div class="row btns">
        <button @click="close(false)">取消</button>
        <button class="primary" @click="close(true)">{{ S.dialog.okText || '确定' }}</button>
      </div>
    </div>
  </div>
  <ProjectList v-if="S.showProjects" />
  <GlossaryModal v-if="S.showGlossary" />
  <TranslateSettings v-if="S.showTranslateSettings" />
  <div class="toasts">
    <div v-for="t in S.toasts" :key="t.id" class="toast" :class="t.type">{{ t.text }}</div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; z-index: 100; }
.box { background: var(--bg2); border: 1px solid var(--line); border-radius: 8px; padding: 16px 20px; min-width: 340px; max-width: 520px; box-shadow: 0 10px 40px rgba(0,0,0,.5); }
h3 { margin: 0 0 8px; font-size: 15px; }
.msg { margin: 0 0 12px; line-height: 1.6; white-space: pre-wrap; }
.btns { justify-content: flex-end; margin-top: 14px; }
.chk { margin-top: 4px; color: var(--dim); }
.toasts { position: fixed; right: 16px; bottom: calc(var(--tl-h, 176px) + 14px); display: flex; flex-direction: column; gap: 6px; z-index: 200; max-width: 420px; }
.toast { background: #2a2f3a; border: 1px solid var(--line); border-left: 4px solid var(--blue); padding: 8px 12px; border-radius: 5px; box-shadow: 0 4px 16px rgba(0,0,0,.4); }
.toast.error { border-left-color: var(--err); }
.toast.ok { border-left-color: var(--ok); }
</style>
