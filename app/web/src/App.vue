<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import { S, boot, undo, redo, flushAll, removeKeyframe, selectedKf, stepPlayhead, jumpKeyframe, setPlayhead, addKeyframeAtPlayhead, hasVideoRef } from './store'
import TopBar from './components/TopBar.vue'
import ToolPanel from './components/ToolPanel.vue'
import CanvasStage from './components/CanvasStage.vue'
import ResultView from './components/ResultView.vue'
import GenPanel from './components/GenPanel.vue'
import RightPanel from './components/RightPanel.vue'
import Timeline from './components/Timeline.vue'
import Dialogs from './components/Dialogs.vue'

function onKey(e) {
  const t = e.target
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return
  if (!S.project || S.dialog) return
  const k = e.key.toLowerCase()
  if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return }
  if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo(); return }
  if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); flushAll(); return }
  if (S.view === 'canvas' && (k === 'arrowleft' || k === 'arrowright')) {
    e.preventDefault()
    const dir = k === 'arrowleft' ? -1 : 1
    if (e.ctrlKey || e.metaKey) jumpKeyframe(dir)
    else stepPlayhead(dir, e.shiftKey)
    return
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return
  if (S.view === 'canvas' && k === 'home') { e.preventDefault(); setPlayhead(0); return }
  if (S.view === 'canvas' && k === 'end') { e.preventDefault(); setPlayhead(S.timeline ? S.timeline.last : 0); return }
  if (S.view === 'canvas' && k === 'k') { addKeyframeAtPlayhead(); return }
  if (k === 'b') S.tool = 'brush'
  else if (k === 'e') S.tool = 'eraser'
  else if (k === 'g') S.tool = 'fill'
  else if (k === 'i') S.tool = 'eyedrop'
  else if (k === '[') S.size = Math.max(1, S.size - (S.size > 20 ? 4 : 1))
  else if (k === ']') S.size = Math.min(200, S.size + (S.size >= 20 ? 4 : 1))
  else if (k === 'delete' && selectedKf.value && selectedKf.value.id !== 'k_first') removeKeyframe(selectedKf.value.id)
}
function beforeUnload(e) {
  if (S.unsavedStrokes || S.projectDirty) { flushAll(); e.preventDefault(); e.returnValue = '' }
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', beforeUnload)
  boot()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <div class="app" :style="{ '--tl-h': S.project && hasVideoRef ? '206px' : '176px' }">
    <TopBar class="a-top" />
    <ToolPanel class="a-tools" v-if="S.project" />
    <div class="a-center" v-if="S.project">
      <CanvasStage v-show="S.view === 'canvas'" />
      <ResultView v-if="S.view === 'result'" />
      <GenPanel />
    </div>
    <div v-else class="a-center loading">{{ S.ready ? '没有打开的项目' : '正在载入…' }}</div>
    <RightPanel class="a-right" v-if="S.project" />
    <Timeline class="a-time" v-if="S.project" />
    <Dialogs />
  </div>
</template>

<style scoped>
.app {
  height: 100%; display: grid;
  grid-template-columns: 252px minmax(0, 1fr) 360px;
  grid-template-rows: auto minmax(0, 1fr) var(--tl-h, 176px);
  grid-template-areas: "top top top" "tools center right" "time time time";
}
.a-top { grid-area: top; }
.a-tools { grid-area: tools; }
.a-center { grid-area: center; position: relative; min-width: 0; min-height: 0; background: #0e1013; display: flex; }
.a-right { grid-area: right; }
.a-time { grid-area: time; }
.loading { align-items: center; justify-content: center; color: var(--dim); }
</style>
