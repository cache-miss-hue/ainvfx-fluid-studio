<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { S, toast, errMsg, loadResults, deleteResult } from '../store'
import { api } from '../api'

const cur = computed(() => S.currentResult)
const params = computed(() => (cur.value && cur.value.params) || {})
const fxVid = ref(null)
const refVid = ref(null)
const overlayOn = ref(false)
const blend = ref('screen')
const exporting = ref(false)
const playing = ref(false)
const t = ref(0)
const dur = ref(0)

const fxUrl = computed(() => (cur.value ? api.mediaUrl(cur.value.file) : ''))
const canOverlay = computed(() => params.value.base_mode === 0 && !!params.value.reference)
const curRef = computed(() => S.project && S.project.reference)
const refOk = computed(() => {
  const r = params.value.reference
  return !!(canOverlay.value && curRef.value && r && curRef.value.file === r.file && curRef.value.original_name === r.original_name)
})
const refUrl = computed(() => api.refFileUrl(S.pid, S.refRev))
const start25 = computed(() => (params.value.reference ? params.value.reference.start25 || 0 : 0))
const isVideoRef = computed(() => params.value.reference && params.value.reference.type === 'video')
const css = computed(() => (blend.value === 'addition' ? 'plus-lighter' : 'screen'))
const showOverlay = computed(() => overlayOn.value && refOk.value)
const aspect = computed(() => (params.value.width && params.value.height ? `${params.value.width} / ${params.value.height}` : '16 / 9'))
const compFile = computed(() => (cur.value && cur.value.composites ? cur.value.composites[blend.value] : null))

watch(cur, () => { playing.value = false; t.value = 0 })

function syncRef(force = false) {
  const f = fxVid.value, r = refVid.value
  if (!f || !r || !showOverlay.value || !isVideoRef.value) return
  const want = start25.value / 25 + f.currentTime
  if (force || Math.abs(r.currentTime - want) > 0.08) { try { r.currentTime = want } catch (_) { /* 未就绪 */ } }
}
function onTime() {
  const f = fxVid.value
  if (!f) return
  t.value = f.currentTime
  syncRef()
}
function onMeta() { dur.value = fxVid.value.duration || 0; syncRef(true) }
function toggle() {
  const f = fxVid.value
  if (!f) return
  if (f.paused) { syncRef(true); f.play() } else f.pause()
}
function onPlay() { playing.value = true; if (refVid.value && showOverlay.value && isVideoRef.value) refVid.value.play().catch(() => {}) }
function onPause() { playing.value = false; if (refVid.value) refVid.value.pause(); syncRef(true) }
function seek(e) {
  const f = fxVid.value
  f.currentTime = Number(e.target.value)
  syncRef(true)
}
watch(showOverlay, (v) => {
  if (v) setTimeout(() => { syncRef(true); if (playing.value && refVid.value) refVid.value.play().catch(() => {}) }, 50)
})
onBeforeUnmount(() => { if (fxVid.value) fxVid.value.pause() })

async function exportOverlay() {
  exporting.value = true
  try {
    const r = await api.overlay(cur.value.file, blend.value)
    await loadResults()
    const hit = S.results.find((x) => x.file === cur.value.file)
    if (hit) S.currentResult = hit
    toast('合成版已导出', 'ok')
    const a = document.createElement('a')
    a.href = api.mediaUrl(r.file); a.download = r.file.split('/').pop()
    document.body.appendChild(a); a.click(); a.remove()
  } catch (e) {
    toast('导出合成版失败：' + errMsg(e), 'error', 8000)
  } finally {
    exporting.value = false
  }
}
function pick(r) { S.currentResult = r }
const label = (r) => {
  const p = r.params || {}
  const c = p.created || ''
  const time = c ? `${c.slice(4, 6)}-${c.slice(6, 8)} ${c.slice(9, 11)}:${c.slice(11, 13)}` : r.file.split('/').pop()
  return `${time} · seed ${p.seed ?? '?'} · ${p.seconds ?? '?'}秒 · ${p.width ?? '?'}×${p.height ?? '?'}`
}
const fname = computed(() => (cur.value ? cur.value.file.split('/').pop() : ''))
</script>

<template>
  <div class="rv">
    <div class="main">
      <div class="head row">
        <button @click="S.view = 'canvas'">← 返回画布</button>
        <b class="grow">生成结果 <span class="dim">{{ fname }}</span></b>
        <a v-if="cur" class="btn" :href="api.mediaUrl(cur.file)" :download="fname">下载 MP4</a>
      </div>

      <div class="player" v-if="cur">
        <div class="stack" :style="{ aspectRatio: aspect }">
          <template v-if="showOverlay">
            <video v-if="isVideoRef" ref="refVid" class="plate" :src="refUrl" muted playsinline preload="auto"></video>
            <img v-else class="plate" :src="refUrl" alt="参考画面" />
          </template>
          <video ref="fxVid" class="fx" :src="fxUrl" :style="{ mixBlendMode: showOverlay ? css : 'normal' }" loop playsinline
            @timeupdate="onTime" @loadedmetadata="onMeta" @play="onPlay" @pause="onPause" @seeked="syncRef(true)" @click="toggle"></video>
        </div>
        <div class="ctl row">
          <button @click="toggle" style="width:64px">{{ playing ? '暂停' : '播放' }}</button>
          <input class="grow" type="range" min="0" :max="dur || 1" step="0.01" :value="t" @input="seek" />
          <span class="dim tm">{{ t.toFixed(2) }} / {{ dur.toFixed(2) }} 秒</span>
        </div>
      </div>

      <div class="ov" v-if="cur && canOverlay">
        <label class="row"><input type="checkbox" v-model="overlayOn" :disabled="!refOk" /> 叠加到参考画面（黑底素材预览）</label>
        <template v-if="refOk">
          <div class="row">
            <span class="dim">混合方式</span>
            <label class="row"><input type="radio" value="screen" v-model="blend" /> 滤色</label>
            <label class="row"><input type="radio" value="addition" v-model="blend" /> 相加</label>
            <div class="grow"></div>
            <button :disabled="exporting" @click="exportOverlay">{{ exporting ? '导出中…' : '导出合成版' }}</button>
            <a v-if="compFile" class="btn" :href="api.mediaUrl(compFile)" :download="compFile.split('/').pop()">下载已导出的{{ blend === 'screen' ? '滤色' : '相加' }}版</a>
          </div>
          <div class="hint">视频参考会按起始帧 {{ start25 }}（{{ (start25 / 25).toFixed(2) }} 秒）与特效同步播放。</div>
        </template>
        <div v-else class="hint warn">这次生成时的参考画面已被替换或移除，无法预览叠加。</div>
      </div>
    </div>

    <aside class="list">
      <b>本项目的历次结果 <span class="badge">{{ S.results.length }}</span></b>
      <div v-if="!S.results.length" class="dim">还没有结果</div>
      <div v-for="r in S.results" :key="r.file" class="it" :class="{ on: cur && cur.file === r.file }" @click="pick(r)">
        <div>{{ label(r) }}</div>
        <div class="dim sm row">{{ r.params && r.params.base_mode === 0 ? '黑底' : r.params && r.params.base_mode === 2 ? '色块化' : '原图' }}
          <span v-if="r.params && r.params.seconds_taken"> · 用时 {{ r.params.seconds_taken }}s</span>
          <span class="grow"></span>
          <button class="small danger x" title="删除这次结果（移到回收站）" @click.stop="deleteResult(r)">删除</button></div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.rv { flex: 1; display: flex; min-width: 0; min-height: 0; }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; padding: 10px 14px; gap: 8px; overflow-y: auto; }
.head { gap: 10px; }
.btn { display: inline-block; padding: 4px 12px; background: var(--accent); color: #1a1007; border-radius: 5px; text-decoration: none; font-weight: 600; user-select: none; }
.player { display: flex; flex-direction: column; gap: 6px; align-items: center; min-height: 0; }
.stack { position: relative; background: #000; max-width: 100%; max-height: calc(100vh - 52px - var(--tl-h, 176px) - 190px); width: 100%; }
.stack { width: auto; height: calc(100vh - 52px - var(--tl-h, 176px) - 190px); max-width: 100%; }
.plate, .fx { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.fx { cursor: pointer; }
.ctl { width: 100%; max-width: 960px; }
.tm { white-space: nowrap; width: 110px; text-align: right; }
.ov { background: var(--bg2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 6px; }
.list { width: 250px; flex: none; border-left: 1px solid var(--line); background: var(--bg2); overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.it { padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; font-size: 12px; }
.it:hover { background: var(--bg3); }
.it.on { border-color: var(--accent); background: rgba(255,122,26,.08); }
.sm { font-size: 11px; }
.x { padding: 0 6px; line-height: 16px; font-size: 11px; }
</style>
