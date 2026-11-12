<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import {
  S, getLayer, peekLayer, opBegin, opEnd, baseUrl, selectedKf, curKid, resolved, isKfEmpty, emptyKfs,
  neighborOf, loadBasePixels, toast, canvasSrc, isPreview, previewFrame, livePreview, ensureKeyframeAtPlayhead,
  addKeyframeAtPlayhead, snapFrame,
} from '../store'
import * as R from '../lib/raster'

const wrap = ref(null)
const strokeCv = ref(null)
const onionCv = ref(null)
const baseImg = ref(null)
const cursor = ref({ x: 0, y: 0, show: false })
const box = ref({ w: 400, h: 225 })
let ro = null

const W = computed(() => S.project.width)
const H = computed(() => S.project.height)
const scale = computed(() => {
  const s = Math.min((box.value.w - 24) / W.value, (box.value.h - 24) / H.value)
  return Math.max(0.1, s)
})
const dispW = computed(() => Math.floor(W.value * scale.value))
const dispH = computed(() => Math.floor(H.value * scale.value))
const cursorD = computed(() => Math.max(4, S.size * scale.value))

const kfEmpty = computed(() => !!curKid.value && isKfEmpty(curKid.value) && !isPreview.value)
const frameText = computed(() => {
  const k = selectedKf.value
  if (S.scrub != null && k) return `拖动中：关键帧移到第 ${S.scrub} 帧（${(S.scrub / 25).toFixed(2)} 秒）`
  if (isPreview.value) {
    const f = previewFrame.value
    return `预览 · 第 ${f} 帧 · ${(f / 25).toFixed(2)} 秒${k ? '' : ' · 不是关键帧'}`
  }
  if (!k) return ''
  return `${k.id === 'k_first' ? '首帧' : k.tail ? '尾帧' : '关键帧'} · 第 ${k.index} 帧 · ${(k.index / 25).toFixed(2)} 秒`
})
// 预览状态下落笔会建在哪一帧（吸附开时是最近的网格点）
const landAt = computed(() => (S.project.snap !== false ? snapFrame(S.playhead) : S.playhead))
const showPreviewTip = computed(() => !selectedKf.value && !S.scrubbing && S.scrub == null)
const previewKind = computed(() => (livePreview.value
  ? (S.project.base_mode === 2 ? '现在显示的是原始画面，建关键帧后显示色块化底图。' : '现在显示的是这一帧的参考画面。')
  : ''))

// ---------- 显示 ----------
let strokeCtx = null
function redrawStrokes(rect) {
  const cv = strokeCv.value
  if (!cv) return
  if (cv.width !== W.value || cv.height !== H.value) { cv.width = W.value; cv.height = H.value }
  strokeCtx = strokeCtx || cv.getContext('2d')
  const L = curKid.value && peekLayer(curKid.value)
  if (!L) { strokeCtx.clearRect(0, 0, cv.width, cv.height); return }
  const id = new ImageData(L.img.data, L.img.width, L.img.height)
  if (rect) strokeCtx.putImageData(id, 0, 0, rect[0], rect[1], rect[2] - rect[0] + 1, rect[3] - rect[1] + 1)
  else { strokeCtx.clearRect(0, 0, cv.width, cv.height); strokeCtx.putImageData(id, 0, 0) }
}

let tmpCv = null
function redrawOnion() {
  const cv = onionCv.value
  if (!cv) return
  if (cv.width !== W.value || cv.height !== H.value) { cv.width = W.value; cv.height = H.value }
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  if (!S.onionOn) return
  const nb = neighborOf('prev')
  const L = nb && peekLayer(nb.id)
  if (!L || L.img.width !== cv.width) return
  tmpCv = tmpCv || document.createElement('canvas')
  tmpCv.width = cv.width; tmpCv.height = cv.height
  tmpCv.getContext('2d').putImageData(new ImageData(L.img.data, L.img.width, L.img.height), 0, 0)
  ctx.globalAlpha = 0.3
  ctx.drawImage(tmpCv, 0, 0)
  ctx.globalAlpha = 1
}

const prevRev = computed(() => {
  const nb = (void S.playhead, neighborOf('prev'))
  return nb ? (S.layerInfo[nb.id] ? S.layerInfo[nb.id].rev : 0) + ':' + nb.id : 'none'
})
const curRev = computed(() => (curKid.value && S.layerInfo[curKid.value] ? S.layerInfo[curKid.value].rev : 0))

watch([curKid, curRev, W, H, () => S.view], async () => { await nextTick(); redrawStrokes() })
watch([prevRev, () => S.onionOn, curKid, W, H, () => resolved.value.length, () => S.view], async () => { await nextTick(); redrawOnion() })
watch(baseUrl, (u) => { if (u) loadBasePixels(u) }, { immediate: true })
const baseFailed = ref(false)
watch(canvasSrc, () => { baseFailed.value = false })

onMounted(() => {
  ro = new ResizeObserver(() => {
    const r = wrap.value.getBoundingClientRect()
    box.value = { w: r.width, h: r.height }
  })
  ro.observe(wrap.value)
  redrawStrokes(); redrawOnion()
})
onBeforeUnmount(() => ro && ro.disconnect())

// ---------- 绘制 ----------
let drawing = false
let last = null
let dirty = null
let eyedropping = false

function toPix(e) {
  const r = strokeCv.value.getBoundingClientRect()
  return [Math.floor(((e.clientX - r.left) / r.width) * W.value), Math.floor(((e.clientY - r.top) / r.height) * H.value)]
}
function rgbNow() { return R.hexToRgb(S.color) || [255, 255, 255] }

async function pickColor(x, y) {
  if (!curKid.value || isPreview.value) return
  const L = getLayer(curKid.value)
  const base = await loadBasePixels(baseUrl.value)
  const rgb = R.sampleComposite(base, L.img, x, y)
  if (rgb) {
    S.color = R.rgbToHex(...rgb)
    if (S.tool === 'eyedrop') S.tool = 'brush'
  }
}

function applyDirty(b) {
  if (!b) return
  dirty = dirty ? R.unionBox(dirty, b[0], b[1], b[2], b[3]) : [b[0], b[1], b[2], b[3]]
}
function flushDirty() {
  if (dirty) { redrawStrokes(dirty); dirty = null }
}

function down(e) {
  if (e.button !== 0 && e.pointerType === 'mouse') return
  if (S.scrubbing || S.scrub != null) return
  e.preventDefault()
  const [x, y] = toPix(e)
  const tool = S.tool
  const eyedrop = tool === 'eyedrop' || e.altKey
  let created = false
  if (!selectedKf.value) {
    // 预览帧上：画笔/填充 = 在这里新建关键帧接着画；橡皮、吸管不建帧（没有可擦的笔触 / 预览图不是最终底图）
    if (eyedrop) { toast('吸管要在关键帧上用（预览画面不是最终底图）。先在这里画一笔或按 K 建关键帧'); return }
    if (tool === 'eraser') { toast('这一帧还不是关键帧，没有可擦的笔触'); return }
    const r = ensureKeyframeAtPlayhead()
    if (!r) return
    created = r.created
  }
  if (eyedrop) { pickColor(x, y); eyedropping = true; return }
  const kid = curKid.value
  const L = getLayer(kid)
  strokeCv.value.setPointerCapture(e.pointerId)
  if (tool === 'fill') {
    opBegin(kid, created)
    const b = R.floodFill(L.img, x, y, rgbNow())
    if (b) redrawStrokes()
    opEnd()
    return
  }
  opBegin(kid, created)
  drawing = true
  last = [x, y]
  applyDirty(R.stamp(L.img, x, y, S.size, rgbNow(), tool === 'eraser' ? 'erase' : 'paint', S.soft))
  flushDirty()
}
function move(e) {
  const r = strokeCv.value.getBoundingClientRect()
  cursor.value = { x: e.clientX - r.left, y: e.clientY - r.top, show: true }
  if (eyedropping) { const [x, y] = toPix(e); pickColor(x, y); return }
  if (!drawing || !curKid.value) return
  const L = getLayer(curKid.value)
  const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : []
  const list = evs.length ? evs : [e]
  for (const ev of list) {
    const [x, y] = toPix(ev)
    applyDirty(R.strokeLine(L.img, last[0], last[1], x, y, S.size, rgbNow(), S.tool === 'eraser' ? 'erase' : 'paint', S.soft))
    last = [x, y]
  }
  flushDirty()
}
function up() {
  eyedropping = false
  if (!drawing) return
  drawing = false
  last = null
  opEnd()
}
function leave() { cursor.value.show = false }

const showCursor = computed(() => cursor.value.show && (S.tool === 'brush' || S.tool === 'eraser'))
function addHere() { addKeyframeAtPlayhead() }
</script>

<template>
  <div class="stage" ref="wrap">
    <div class="cv" :style="{ width: dispW + 'px', height: dispH + 'px' }">
      <img ref="baseImg" class="layer base" :src="canvasSrc" :style="{ opacity: S.baseOpacity }" draggable="false" alt=""
        @error="baseFailed = true" @load="baseFailed = false" />
      <div v-if="baseFailed && isPreview && livePreview" class="nofr">这一帧超出了参考视频的长度（没有画面）</div>
      <canvas ref="onionCv" class="layer onion"></canvas>
      <canvas ref="strokeCv" class="layer strokes" :class="{ eyedrop: S.tool === 'eyedrop', fillc: S.tool === 'fill' }"
        @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up" @pointerleave="leave"></canvas>
      <div v-if="showCursor" class="ring" :style="{ width: cursorD + 'px', height: cursorD + 'px', left: cursor.x + 'px', top: cursor.y + 'px' }"></div>
      <div v-if="showPreviewTip" class="emptytip pv">
        <b>第 {{ S.playhead }} 帧还不是关键帧</b>
        <span>直接用画笔或填充画，就会在{{ landAt !== S.playhead ? `最近的吸附帧（第 ${landAt} 帧）` : '这一帧' }}新建关键帧。{{ previewKind }}</span>
      </div>
      <div v-else-if="kfEmpty" class="emptytip">
        <b>这一帧没画 = 此刻无特效</b>
        <span>在这个关键帧上画出这一刻特效的形状和颜色；不画就表示这一刻什么都没有。</span>
      </div>
    </div>
    <div class="info top-l">{{ frameText }} · {{ W }}×{{ H }}
      <button v-if="showPreviewTip" class="small addhere" @click="addHere">＋ 在这里建关键帧（K）</button></div>
    <div class="info top-r" v-if="emptyKfs.length" :title="'没画的关键帧：' + emptyKfs.map((k) => k.index).join('、')">
      <span class="warn">⚠ {{ emptyKfs.length }} 个关键帧没画（= 此刻无特效）</span>
    </div>
  </div>
</template>

<style scoped>
.stage { flex: 1; min-width: 0; min-height: 0; display: flex; align-items: center; justify-content: center; position: relative; overflow: hidden;
  background: repeating-conic-gradient(#14161a 0% 25%, #101215 0% 50%) 0 0 / 24px 24px; }
.cv { position: relative; background: #000; box-shadow: 0 0 0 1px #3a4050, 0 8px 30px rgba(0,0,0,.6); flex: none; }
.layer { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.base { object-fit: fill; pointer-events: none; }
.onion { pointer-events: none; }
.strokes { cursor: none; touch-action: none; }
.strokes.eyedrop { cursor: crosshair; }
.strokes.fillc { cursor: cell; }
.ring { position: absolute; border: 1px solid #fff; border-radius: 50%; box-shadow: 0 0 0 1px #000; transform: translate(-50%, -50%); pointer-events: none; mix-blend-mode: difference; }
.emptytip { position: absolute; left: 50%; top: 14px; transform: translateX(-50%); background: rgba(70, 20, 20, .88); border: 1px solid var(--err);
  color: #ffd0d0; padding: 8px 16px; border-radius: 8px; pointer-events: none; text-align: center; display: flex; flex-direction: column; gap: 2px; max-width: 80%; }
.emptytip b { font-size: 16px; }
.emptytip span { font-size: 12px; opacity: .85; }
.emptytip.pv { background: rgba(20, 40, 70, .85); border-color: var(--blue); color: #d6e8ff; }
.nofr { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--dim); pointer-events: none; }
.info { position: absolute; top: 8px; font-size: 12px; background: rgba(0,0,0,.55); padding: 2px 8px; border-radius: 4px; pointer-events: none; }
.addhere { pointer-events: auto; margin-left: 8px; }
.top-l { left: 10px; }
.top-r { right: 10px; }
</style>
