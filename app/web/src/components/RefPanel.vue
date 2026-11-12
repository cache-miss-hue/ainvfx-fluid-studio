<script setup>
import { ref, computed, watch } from 'vue'
import { S, uploadReference, uploadFrameRef, removeFrameRef, removeReference, confirmDialog, toast } from '../store'
import { api } from '../api'

const over = ref(false)
const fileInput = ref(null)
const vid = ref(null)

const ref0 = computed(() => S.project.reference)
const isVideo = computed(() => ref0.value && ref0.value.type === 'video')
const need = computed(() => 24 * Number(S.project.seconds) + 1)
// 起始帧最多到“往后还够所选时长”的位置
const maxFrame = computed(() => (isVideo.value ? Math.max(0, (ref0.value.frames25 || 1) - need.value) : 0))
const tooShort = computed(() => isVideo.value && (ref0.value.frames25 || 0) < need.value)
const start = computed(() => (ref0.value ? ref0.value.start25 || 0 : 0))
const dragVal = ref(null)          // 拖滑条时只显示数字，松手才改起始帧（避免一路重新抽帧）
const shown = computed(() => (dragVal.value != null ? dragVal.value : start.value))

function pickFile(e) {
  const f = e.target.files && e.target.files[0]
  if (f) uploadReference(f)
  e.target.value = ''
}
function onDrop(e) {
  over.value = false
  const f = e.dataTransfer.files && e.dataTransfer.files[0]
  if (f) uploadReference(f)
}
async function onRemove() {
  if (await confirmDialog('移除参考画面？（笔触不受影响）', '移除')) removeReference()
}

function setStart(v) {
  v = Math.max(0, Math.min(maxFrame.value, Math.round(Number(v) || 0)))
  dragVal.value = null
  S.project.reference.start25 = v
}
function step(d) { setStart(start.value + d) }
watch(start, (n) => { if (vid.value && isVideo.value) try { vid.value.currentTime = n / 25 } catch (_) { /* 视频未就绪 */ } })
function onVideoLoaded() { if (vid.value) vid.value.currentTime = start.value / 25 }
// 在上面的播放器里找到想要的画面后，一键把它设为起始帧
function useVideoTime() {
  if (!vid.value) return
  vid.value.pause()
  setStart(Math.round(vid.value.currentTime * 25))
  if (Math.round(vid.value.currentTime * 25) > maxFrame.value) toast(`起始帧最多到第 ${maxFrame.value} 帧（再往后视频就不够 ${S.project.seconds} 秒了）`)
}

// 起始帧精确预览：与生成实际取到的第一帧完全一致（同一套取帧方式）
const previewUrl = computed(() => (isVideo.value ? api.clipUrl(S.pid, start.value, 0, S.baseRev) : ''))
const refFile = computed(() => (ref0.value ? api.refFileUrl(S.pid, S.refRev) : ''))

const frameSlots = [{ id: 'first', name: '首帧图' }, { id: 'tail', name: '尾帧图' }]
const slotInfo = (id) => (S.project.frame_refs && S.project.frame_refs[id]) || null
function pickSlot(id, e) {
  const f = e.target.files && e.target.files[0]
  if (f) uploadFrameRef(id, f)
  e.target.value = ''
}
function dropSlot(id, e) {
  const f = e.dataTransfer.files && e.dataTransfer.files[0]
  if (f) uploadFrameRef(id, f)
}

const modes = [
  { id: 0, name: '黑底', desc: '纯黑背景，只出特效（适合之后叠加到别的画面）。' },
  { id: 1, name: '原图', desc: '参考画面原样作底图，特效生成在它上面。' },
  { id: 2, name: '色块化', desc: '把参考画面模糊并压成少量色块，减少细节干扰。' },
]
</script>

<template>
  <div class="ref">
    <div class="drop" :class="{ over }" @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop" @click="fileInput.click()">
      <input ref="fileInput" type="file" hidden accept="image/*,video/*,.mkv,.mov" @change="pickFile" />
      <span v-if="!ref0">拖放图片或视频到这里，或点击选择</span>
      <span v-else>点击或拖放可替换参考画面</span>
    </div>

    <template v-if="ref0">
      <div class="row">
        <span class="badge">{{ isVideo ? '视频' : '图片' }}</span>
        <span class="grow nm" :title="ref0.original_name">{{ ref0.original_name }}</span>
        <span class="dim">{{ ref0.width }}×{{ ref0.height }}</span>
        <button class="small danger" @click="onRemove">移除</button>
      </div>
      <img v-if="!isVideo" class="thumb" :src="refFile" alt="参考图" />
      <template v-else>
        <video ref="vid" class="thumb" :src="refFile" muted controls preload="auto" @loadedmetadata="onVideoLoaded"></video>
        <button class="small" @click="useVideoTime" title="在上面的播放器里拖到想要的画面，点这里把它设为特效的起始帧">⤓ 用播放器当前画面作起始帧</button>
        <div class="field">
          <span class="lbl">起始帧（25fps 帧号，0–{{ maxFrame }}；约 {{ (shown / 25).toFixed(2) }} 秒）· 也可以在底部“源视频”条上拖橙色框</span>
          <div class="row">
            <button class="small" @click="step(-1)" title="后退一帧">◀</button>
            <input class="grow" type="range" :min="0" :max="maxFrame" :value="shown" @input="dragVal = Number($event.target.value)" @change="setStart($event.target.value)" />
            <button class="small" @click="step(1)" title="前进一帧">▶</button>
            <input type="number" :min="0" :max="maxFrame" :value="shown" @change="setStart($event.target.value)" style="width:64px" />
          </div>
          <div v-if="tooShort" class="hint warn">这段视频不到 {{ S.project.seconds }} 秒，请缩短时长。</div>
        </div>
        <div class="field">
          <span class="lbl">起始帧精确预览（与生成使用的画面一致）</span>
          <img class="thumb" :src="previewUrl" alt="起始帧预览" />
        </div>
        <div class="hint">时长 {{ ref0.duration ? ref0.duration.toFixed(2) : '?' }} 秒 · 原始 {{ ref0.fps ? ref0.fps.toFixed(2) : '?' }} fps（统一按 25fps 取帧）</div>
      </template>
      <div v-if="S.videoWarning" class="warnbox">{{ S.videoWarning }}</div>
    </template>

    <div class="field">
      <span class="lbl">首帧 / 尾帧图片（可选，分别作为第一帧、最后一帧的底图；中间关键帧用上面的参考画面，没有就用首帧图）</span>
      <div class="row slots">
        <div v-for="s in frameSlots" :key="s.id" class="slot" @dragover.prevent @drop.prevent="dropSlot(s.id, $event)">
          <label class="slotbtn">
            <input type="file" hidden accept="image/*" @change="pickSlot(s.id, $event)" />
            <img v-if="slotInfo(s.id)" class="slotimg" :src="api.frameRefUrl(S.pid, s.id, S.refRev)" :alt="s.name" />
            <span v-else>{{ s.name }}：点击或拖入</span>
          </label>
          <div v-if="slotInfo(s.id)" class="row"><span class="grow nm dim">{{ s.name }} · {{ slotInfo(s.id).original_name }}</span>
            <button class="small danger" @click="removeFrameRef(s.id)">移除</button></div>
        </div>
      </div>
    </div>

    <div class="field">
      <span class="lbl">底图模式</span>
      <label v-for="m in modes" :key="m.id" class="mode" :class="{ on: S.project.base_mode === m.id }">
        <input type="radio" :value="m.id" v-model.number="S.project.base_mode" />
        <span><b>{{ m.id }} {{ m.name }}</b><br /><span class="dim">{{ m.desc }}</span></span>
      </label>
      <div v-if="S.project.base_mode !== 0 && !ref0 && !(S.project.frame_refs && (S.project.frame_refs.first || S.project.frame_refs.tail))" class="hint warn">还没有参考画面，现在底图是黑色。上传后才会显示。</div>
    </div>

    <div v-if="S.project.base_mode === 2" class="field adv">
      <div class="row"><span class="lbl2">模糊半径 {{ S.project.blur_radius }}</span>
        <input class="grow" type="range" min="1" max="31" step="1" v-model.number="S.project.blur_radius" /></div>
      <div class="row"><span class="lbl2">模糊强度 {{ Number(S.project.blur_sigma).toFixed(1) }}</span>
        <input class="grow" type="range" min="0.1" max="10" step="0.1" v-model.number="S.project.blur_sigma" /></div>
      <div class="row"><span class="lbl2">颜色数 {{ S.project.colors }}</span>
        <input class="grow" type="range" min="2" max="32" step="1" v-model.number="S.project.colors" /></div>
    </div>
    <div class="hint">底图只用于显示和生成时的参考；笔触与底图分开保存，换底图不会丢笔触。</div>
  </div>
</template>

<style scoped>
.ref { display: flex; flex-direction: column; gap: 8px; }
.drop { border: 1.5px dashed #4a5162; border-radius: 8px; padding: 12px; text-align: center; color: var(--dim); cursor: pointer; }
.drop:hover, .drop.over { border-color: var(--accent); color: var(--accent2); background: rgba(255,122,26,.06); }
.slots { align-items: flex-start; }
.slot { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.slotbtn { display: flex; align-items: center; justify-content: center; min-height: 60px; border: 1.5px dashed #4a5162; border-radius: 6px; cursor: pointer; color: var(--dim); font-size: 12px; text-align: center; overflow: hidden; }
.slotbtn:hover { border-color: var(--accent); color: var(--accent2); }
.slotimg { width: 100%; max-height: 90px; object-fit: contain; background: #000; display: block; }
.nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thumb { width: 100%; max-height: 190px; object-fit: contain; background: #000; border-radius: 5px; display: block; }
.mode { display: flex; gap: 8px; align-items: flex-start; padding: 5px 8px; border: 1px solid var(--line); border-radius: 6px; margin-bottom: 4px; }
.mode.on { border-color: var(--accent); background: rgba(255,122,26,.07); }
.mode input { margin-top: 4px; }
.warnbox { background: #473a14; border: 1px solid var(--warn); color: #ffe0a0; padding: 6px 9px; border-radius: 5px; font-size: 12px; }
.adv { display: flex; flex-direction: column; gap: 4px; }
.lbl2 { width: 92px; font-size: 12px; color: var(--dim); }
</style>
