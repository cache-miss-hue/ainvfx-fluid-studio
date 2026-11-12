<script setup>
import { ref, computed } from 'vue'
import {
  S, resolved, selectedKf, isKfEmpty, selectKeyframe, setPlayhead, settlePlayhead, addKeyframeAtPlayhead, removeKeyframe,
  applyScheme, moveKeyframe, setSnap, snapFrame, hiddenKfs, removeHiddenKeyframes, hasVideoRef, livePreview, clipUrl,
} from '../store'
import { stepOnGrid } from '../lib/keyframes'
import { api } from '../api'

const track = ref(null)
const ovEl = ref(null)
const last = computed(() => (S.timeline ? S.timeline.last : 24))
const total = computed(() => last.value + 1)
const pct = (f) => (f / last.value) * 100
const snapOn = computed(() => S.project.snap !== false)

const secTicks = computed(() => {
  const t = []
  for (let s = 0; s * 25 <= last.value; s++) t.push({ f: s * 25, label: s + ' 秒' })
  return t
})
const minorTicks = computed(() => {
  const t = []
  for (let f = 0; f <= last.value; f += 5) if (f % 25) t.push(f)
  return t
})
const gridTicks = computed(() => (S.timeline && snapOn.value ? S.timeline.grid : []))

const schemes = [
  { id: 0, name: '只首帧' },
  { id: 1, name: '首尾' },
  { id: 2, name: '每秒一帧' },
]

function frameFromEvent(e) {
  const r = track.value.getBoundingClientRect()
  return Math.round(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * last.value)
}

// 拖动通用收尾：松手、被系统打断（pointercancel）、丢失捕获时都结束，不会“粘住”
function pointerDrag(el, e, onMove, onEnd) {
  try { el.setPointerCapture(e.pointerId) } catch (_) { /* 已释放 */ }
  let done = false
  const evs = ['pointerup', 'pointercancel', 'lostpointercapture']
  const end = (ev) => {
    if (done) return
    done = true
    el.removeEventListener('pointermove', onMove)
    for (const t of evs) el.removeEventListener(t, end)
    onEnd(ev)
  }
  el.addEventListener('pointermove', onMove)
  for (const t of evs) el.addEventListener(t, end)
}

// 拖动标尺 = 移动播放头，画布实时显示这一帧的画面；松手后吸附到最近的可放关键帧的帧
function rulerDown(e) {
  if (e.target.closest('.kf')) return
  if (e.pointerType === 'mouse' && e.button !== 0) return
  e.preventDefault()
  S.scrubbing = true
  setPlayhead(frameFromEvent(e))
  pointerDrag(e.currentTarget, e, (ev) => setPlayhead(frameFromEvent(ev)), () => { S.scrubbing = false; settlePlayhead() })
}
// 双击时间轴 = 在那里加关键帧
function onDbl(e) {
  if (e.target.closest('.kf')) return
  addKeyframeAtPlayhead(frameFromEvent(e))
}
// 拖动时松手会落到的帧（吸附开时）
const ghost = computed(() => {
  if (!S.scrubbing || !snapOn.value) return null
  const g = snapFrame(S.playhead)
  return g !== S.playhead ? g : null
})

// 关键帧：点击选中（播放头跳过去）；拖动移动，拖动中画布预览新位置的画面（首帧、尾帧不可拖）
const drag = ref(null) // {kid, f}
function kfDown(e, k) {
  e.preventDefault()
  e.stopPropagation()
  selectKeyframe(k.id)
  if (k.id === 'k_first' || k.tail) return
  const x0 = e.clientX
  let moved = false
  pointerDrag(e.currentTarget, e, (ev) => {
    if (!moved && Math.abs(ev.clientX - x0) < 4) return
    moved = true
    let f = Math.max(1, Math.min(last.value - 1, frameFromEvent(ev)))
    if (snapOn.value) {
      f = snapFrame(f)
      if (f >= last.value) f = stepOnGrid(last.value, -1, S.timeline.grid)
      if (f <= 0) f = 1
    }
    drag.value = { kid: k.id, f }
    S.scrub = f
  }, () => {
    const d = drag.value
    drag.value = null
    S.scrub = null
    if (moved && d) moveKeyframe(k.id, d.f)
  })
}
const posOf = (k) => (drag.value && drag.value.kid === k.id ? drag.value.f : k.index)

// 时间轴缩略图（参考视频从起始帧往后的画面）
const FILM_N = 12
const film = computed(() => {
  if (!livePreview.value) return []
  return Array.from({ length: FILM_N }, (_, i) => clipUrl(Math.round(((i + 0.5) * last.value) / FILM_N)))
})

// ---------- 整段参考视频：拖选框 = 选起始帧 ----------
const ref0 = computed(() => S.project.reference)
const srcFrames = computed(() => (hasVideoRef.value ? Math.max(1, ref0.value.frames25 || 1) : 1))
const maxStart = computed(() => Math.max(0, srcFrames.value - total.value))
const startLocal = ref(null)          // 拖动中的起始帧（松手才写进项目，避免拖动途中反复抽帧）
const start = computed(() => (startLocal.value != null ? startLocal.value : ref0.value ? ref0.value.start25 || 0 : 0))
const winLeft = computed(() => (start.value / srcFrames.value) * 100)
const winW = computed(() => Math.min(100, (total.value / srcFrames.value) * 100))
const tooShort = computed(() => hasVideoRef.value && srcFrames.value < total.value)
const OV_N = 16
const ovThumbs = computed(() => {
  if (!hasVideoRef.value) return []
  return Array.from({ length: OV_N }, (_, i) => api.refFrameUrl(S.pid, Math.round(((i + 0.5) * (srcFrames.value - 1)) / OV_N), S.refRev, 160))
})
const tipFrame = ref(null)
let tipTimer = null
function showTip(f) {               // 拖动中的起始帧小图：最多每 150ms 换一次，免得一路请求
  if (tipTimer) return
  tipFrame.value = f
  tipTimer = setTimeout(() => { tipTimer = null; if (startLocal.value != null) tipFrame.value = startLocal.value }, 150)
}
function setStart(v) {
  if (!ref0.value) return
  ref0.value.start25 = Math.max(0, Math.min(maxStart.value, Math.round(v)))
}
function ovDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return
  e.preventDefault()
  const r = ovEl.value.getBoundingClientRect()
  const toFrame = (x) => ((x - r.left) / r.width) * srcFrames.value
  const grab = e.target.closest('.win') ? toFrame(e.clientX) - start.value : total.value / 2
  const upd = (ev) => {
    startLocal.value = Math.max(0, Math.min(maxStart.value, Math.round(toFrame(ev.clientX) - grab)))
    showTip(startLocal.value)
  }
  upd(e)
  pointerDrag(e.currentTarget, e, upd, () => {
    if (startLocal.value != null) setStart(startLocal.value)
    startLocal.value = null
    tipFrame.value = null
  })
}

const sec = computed(() => (S.playhead / 25).toFixed(2))
const canDel = computed(() => selectedKf.value && selectedKf.value.id !== 'k_first')
</script>

<template>
  <section class="tl">
    <div class="bar">
      <div class="row grp">
        <span class="dim">方案</span>
        <button v-for="s in schemes" :key="s.id" :class="{ on: S.project.scheme === s.id }" @click="applyScheme(s.id)">{{ s.name }}</button>
        <span v-if="S.project.scheme === 'custom'" class="badge">自定义</span>
      </div>
      <div class="row grp">
        <button @click="addKeyframeAtPlayhead()" title="在播放头位置加一个关键帧（K；也可以双击时间轴，或直接在画布上画）">+ 加帧</button>
        <button class="danger" :disabled="!canDel" @click="removeKeyframe(selectedKf.id)" title="删除播放头所在的关键帧（Delete）">删除此帧</button>
      </div>
      <label class="row"><input type="checkbox" :checked="snapOn" @change="setSnap($event.target.checked)" /> 吸附到 8k+1 网格（推荐）</label>
      <button v-if="hiddenKfs.length" class="small warnbtn" @click="removeHiddenKeyframes"
        :title="'这些关键帧超出了当前时长，或开吸附后与别的帧落到同一帧号，所以不参与生成。点击删除它们。'">
        ⚠ {{ hiddenKfs.length }} 个关键帧不参与生成 · 清理</button>
      <div class="grow"></div>
      <div class="pos">
        第 <b>{{ S.playhead }}</b> 帧 · <b>{{ sec }}</b> 秒
        <span v-if="hasVideoRef" class="dim">· 源视频第 {{ start + S.playhead }} 帧</span>
        <span :class="selectedKf ? 'kfon' : 'dim'">&nbsp;{{ selectedKf ? '· 关键帧' : '· 预览（不是关键帧）' }}&nbsp;</span>
        <span class="dim">/ 共 {{ total }} 帧</span>
      </div>
    </div>

    <div v-if="hasVideoRef" class="ovrow">
      <span class="ovlbl dim" :title="`参考视频共 ${srcFrames} 帧（按 25 帧/秒计）`">源视频</span>
      <div class="ov" ref="ovEl" @pointerdown="ovDown" title="拖动橙色框选择从源视频的哪里开始取画面（= 起始帧）">
        <div class="film ovfilm"><img v-for="(u, i) in ovThumbs" :key="i" :src="u" alt="" draggable="false" /></div>
        <div class="win" :style="{ left: winLeft + '%', width: winW + '%' }"></div>
        <div v-if="tipFrame != null" class="tip" :style="{ left: winLeft + '%' }">
          <img :src="api.refFrameUrl(S.pid, tipFrame, S.refRev, 160)" alt="" />
          <span>起始帧 {{ tipFrame }}（{{ (tipFrame / 25).toFixed(2) }} 秒）</span>
        </div>
      </div>
      <div class="ovinfo">
        <button class="small" @click="setStart(start - 1)" title="起始帧往前一帧">◀</button>
        <span>起始帧 <b>{{ start }}</b>（{{ (start / 25).toFixed(2) }} 秒）</span>
        <button class="small" @click="setStart(start + 1)" title="起始帧往后一帧">▶</button>
        <span v-if="tooShort" class="warn">视频比所选时长短</span>
      </div>
    </div>

    <div class="area">
      <div class="trackbox" ref="track" @pointerdown="rulerDown" @dblclick="onDbl">
        <div class="ruler">
          <i v-for="f in minorTicks" :key="'m' + f" class="tick minor" :style="{ left: pct(f) + '%' }"></i>
          <i v-for="g in gridTicks" :key="'g' + g" class="tick grid" :style="{ left: pct(g) + '%' }"></i>
          <template v-for="t in secTicks" :key="'s' + t.f">
            <i class="tick sec" :style="{ left: pct(t.f) + '%' }"></i>
            <span class="tl-lbl" :style="{ left: pct(t.f) + '%' }">{{ t.label }}<em>{{ t.f }}</em></span>
          </template>
          <span class="tl-lbl endl" :style="{ left: '100%' }"><em>尾 {{ last }}</em></span>
        </div>
        <div class="lane">
          <div v-if="film.length" class="film"><img v-for="(u, i) in film" :key="i" :src="u" alt="" draggable="false" /></div>
          <div v-for="k in resolved" :key="k.id" class="kf"
            :class="{ sel: selectedKf && k.id === selectedKf.id, empty: isKfEmpty(k.id), fixed: k.id === 'k_first' || k.tail }"
            :style="{ left: pct(posOf(k)) + '%' }" @pointerdown="kfDown($event, k)"
            :title="`第 ${posOf(k)} 帧（${(posOf(k) / 25).toFixed(2)} 秒）${isKfEmpty(k.id) ? ' · 没画 = 此刻无特效' : ''}`">
            <i class="dia"></i>
            <span class="kn">{{ posOf(k) }}</span>
          </div>
        </div>
        <div v-if="ghost != null" class="ghost" :style="{ left: pct(ghost) + '%' }" title="松手后会停在这一帧（吸附）"></div>
        <div class="head" :style="{ left: pct(S.scrub != null ? S.scrub : S.playhead) + '%' }"><i></i></div>
      </div>
      <div class="legend dim">
        <span><i class="dia mini"></i> 已画</span>
        <span><i class="dia mini hollow"></i> 没画（= 此刻无特效）</span>
        <span>拖标尺看画面 · 在画布上直接画 = 在这一帧建关键帧 · 双击时间轴或按 K 加帧 · ←/→ 跳格，Shift+←/→ 逐帧，Ctrl+←/→ 跳关键帧</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.tl { background: var(--bg2); border-top: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; padding: 6px 14px 6px; gap: 5px; }
.bar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.grp { gap: 5px; }
.pos { font-size: 13px; white-space: nowrap; }
.kfon { color: var(--accent2); font-weight: 600; }
.warnbtn { border-color: var(--warn); color: var(--warn); }
.ovrow { display: flex; align-items: center; gap: 8px; padding: 0 0 0 14px; }
.ovlbl { font-size: 11px; flex: none; }
.ov { position: relative; flex: 1; height: 24px; background: #0e1013; border-radius: 4px; cursor: pointer; touch-action: none; }
.ovinfo { display: flex; align-items: center; gap: 5px; font-size: 12px; white-space: nowrap; flex: none; }
.ovinfo .warn { color: var(--warn); }
.win { position: absolute; top: -2px; bottom: -2px; border: 2px solid var(--accent); border-radius: 4px; background: rgba(255,122,26,.18); cursor: grab; min-width: 6px; }
.tip { position: absolute; bottom: 30px; transform: translateX(-10%); background: #000; border: 1px solid var(--line); border-radius: 5px; padding: 3px; z-index: 6; pointer-events: none; display: flex; flex-direction: column; align-items: center; gap: 2px; }
.tip img { width: 160px; display: block; }
.tip span { font-size: 11px; white-space: nowrap; }
.film { position: absolute; inset: 0; display: flex; overflow: hidden; border-radius: 4px; opacity: .5; pointer-events: none; }
.film img { flex: 1 1 0; min-width: 0; height: 100%; object-fit: cover; display: block; border-right: 1px solid rgba(0,0,0,.5); }
.ovfilm { opacity: .7; }
.area { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 4px; padding: 0 26px 0 14px; }
.trackbox { position: relative; flex: 1; min-height: 70px; cursor: pointer; touch-action: none; }
.ruler { position: absolute; left: 0; right: 0; top: 0; height: 30px; border-bottom: 1px solid var(--line); }
.tick { position: absolute; bottom: 0; width: 1px; background: #4a5162; height: 6px; }
.tick.sec { height: 16px; background: #8a93a8; }
.tick.grid { height: 10px; background: #7b5a2a; }
.tl-lbl { position: absolute; top: 0; font-size: 11px; color: var(--dim); transform: translateX(3px); white-space: nowrap; line-height: 13px; }
.tl-lbl em { font-style: normal; color: #6f778a; margin-left: 4px; font-size: 10px; }
.tl-lbl.endl { transform: translateX(-100%); margin-left: -4px; }
.lane { position: absolute; left: 0; right: 0; top: 34px; bottom: 0; background: rgba(255,255,255,.02); border-radius: 4px; }
.kf { position: absolute; top: 4px; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; cursor: grab; z-index: 3; }
.kf.fixed { cursor: pointer; }
.dia { display: block; width: 18px; height: 18px; background: var(--accent); transform: rotate(45deg) scale(.78); border: 2px solid #ffd2a8; }
.dia.mini { width: 11px; height: 11px; display: inline-block; vertical-align: middle; border-width: 1px; }
.kf.empty .dia, .dia.hollow { background: rgba(0,0,0,.55); border-color: var(--err); }
.kf.sel .dia { box-shadow: 0 0 0 3px rgba(76,154,255,.9); border-color: #fff; }
.kn { font-size: 11px; margin-top: 3px; color: var(--text); text-shadow: 0 0 3px #000, 0 0 3px #000; }
.kf.sel .kn { color: #fff; font-weight: 600; }
.ghost { position: absolute; top: 0; bottom: 0; width: 0; border-left: 2px dashed rgba(76,154,255,.55); z-index: 4; pointer-events: none; }
.head { position: absolute; top: 0; bottom: 0; width: 0; z-index: 5; pointer-events: none; }
.head::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; border-left: 2px solid var(--blue); }
.head i { position: absolute; left: -6px; top: 0; width: 0; height: 0; border-left: 7px solid transparent; border-right: 7px solid transparent; border-top: 10px solid var(--blue); }
.legend { display: flex; gap: 18px; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
