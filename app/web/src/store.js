// 全局状态与动作：项目、关键帧、笔触层（含撤销/自动保存）、任务、提示词。
import { reactive, computed, watch } from 'vue'
import { api } from './api'
import * as R from './lib/raster'
import { snapTo, resolveKeyframes, stepOnGrid } from './lib/keyframes'

const HISTORY_LIMIT = 60
const AUTOSAVE_STROKES_MS = 800
const AUTOSAVE_PROJECT_MS = 700
const TERMINAL = ['done', 'error', 'cancelled']

export const hasChinese = (s) => /[㐀-鿿豈-﫿　-〿＀-￯]/.test(s || '')

export const S = reactive({
  ready: false,
  pid: null,
  project: null,
  meta: null,
  status: { engine: 'unknown', engine_error: '', first_load_pending: true, queue: [] },
  wsOk: false,
  selfcheck: null,
  timeline: null,            // {seconds,total,last,grid}
  videoWarning: null,
  // 正在编辑的关键帧 = 播放头所在帧上的关键帧（见 selectedKf）；播放头不在关键帧上时是“预览”状态
  playhead: 0,
  scrub: null,               // 拖动关键帧菱形时临时预览的帧号（松手后清空）
  scrubbing: false,          // 正在拖动标尺/播放头
  clipStart: 0,              // 时间轴预览用的起始帧（参考视频起始帧的防抖副本，避免拖滑条时反复抽帧）
  tool: 'brush',             // brush / eraser / fill / eyedrop
  color: '#ff7814',
  size: 14,
  soft: false,
  onionOn: true,
  baseOpacity: 1,
  layerInfo: {},             // kid -> {empty, rev}
  unsavedStrokes: false,
  projectDirty: false,
  baseRev: 1,
  refRev: 1,
  view: 'canvas',            // canvas / result
  results: [],
  currentResult: null,
  genJob: null,
  genBusy: false,
  translating: {},
  promptNotice: '',
  promptWarnings: [],
  toasts: [],
  dialog: null,
  showProjects: false,
  showGlossary: false,
  showTranslateSettings: false,
  projectList: [],
  historyRev: 0,             // 撤销/重做可用性刷新用
  lan: null,                 // 局域网模式：{enabled, token, urls}
})

// ---------------- 提示 / 对话框 ----------------
let toastSeq = 0
export function toast(text, type = 'info', ms = 4200) {
  const id = ++toastSeq
  S.toasts.push({ id, text, type })
  setTimeout(() => { S.toasts = S.toasts.filter((t) => t.id !== id) }, type === 'error' ? ms + 3000 : ms)
}
export function errMsg(e) {
  return (e && e.message) || '出了点问题，请重试'
}
export function confirmDialog(message, okText = '确定', title = '请确认', check = null) {
  // check: 可选的复选框文字（如“本项目不再提醒”）；带复选框时 resolve 为 {ok, checked}
  return new Promise((resolve) => { S.dialog = { kind: 'confirm', title, message, okText, check, checked: false, resolve } })
}
export function inputDialog(title, value = '', message = '') {
  return new Promise((resolve) => { S.dialog = { kind: 'input', title, message, value, resolve } })
}

// ---------------- 时间轴 ----------------
const tlCache = new Map()
async function fetchTimeline(seconds, scheme) {
  const key = `${seconds}:${scheme == null ? '' : scheme}`
  if (tlCache.has(key)) return tlCache.get(key)
  const r = await api.timeline(seconds, scheme)
  const tl = { seconds, total: r.total, last: r.last, grid: r.grid, scheme_indices: r.scheme_indices }
  tlCache.set(key, tl)
  return tl
}

export function snapFrame(idx) {
  return S.timeline ? snapTo(idx, S.timeline.grid) : idx
}

// 与后端 projects.resolved_keyframes 同一规则（lib/keyframes.js，两边用同一份测试数据校验）
export const resolved = computed(() => resolveKeyframes(S.project, S.timeline))

// 播放头所在帧上的关键帧就是正在编辑的帧；没有 = 预览状态（落笔会在这里新建关键帧）
export const selectedKf = computed(() => resolved.value.find((k) => k.index === S.playhead) || null)
export const curKid = computed(() => (selectedKf.value ? selectedKf.value.id : null))
export const emptyKfs = computed(() => resolved.value.filter((k) => isKfEmpty(k.id)))
// 存在但当前不参与生成的关键帧（超出时长，或吸附后与别的帧落在同一帧号）
export const hiddenKfs = computed(() => {
  const p = S.project
  if (!p) return []
  const ids = new Set(resolved.value.map((k) => k.id))
  return p.keyframes.filter((k) => !ids.has(k.id))
})

// 参考视频时间轴预览：有参考视频且底图模式不是黑底时，画布在非关键帧处显示该帧的参考画面
export const hasVideoRef = computed(() => !!(S.project && S.project.reference && S.project.reference.type === 'video'))
export const hasFrameRefs = computed(() => !!(S.project && S.project.frame_refs && (S.project.frame_refs.first || S.project.frame_refs.tail)))
export const livePreview = computed(() => hasVideoRef.value && S.project.base_mode !== 0)
export function clipUrl(frame) {
  return api.clipUrl(S.pid, S.clipStart, frame, S.baseRev)
}
let clipTimer = null
watch(() => (S.project && S.project.reference ? S.project.reference.start25 || 0 : 0), (v) => {
  clearTimeout(clipTimer)
  clipTimer = setTimeout(() => { S.clipStart = v }, 350)
})

export function isKfEmpty(kid) {
  const i = S.layerInfo[kid]
  return i ? i.empty : true
}

// ---------------- 笔触层 ----------------
const layers = new Map() // kid -> {img, undo, redo, dirty, timer, saving}

export function getLayer(kid) {
  let L = layers.get(kid)
  if (!L) {
    L = { img: R.createLayer(S.project.width, S.project.height), undo: [], redo: [], dirty: false, timer: null, saving: Promise.resolve() }
    layers.set(kid, L)
  }
  if (!S.layerInfo[kid]) S.layerInfo[kid] = { empty: true, rev: 0 }
  return L
}
export function peekLayer(kid) { return layers.get(kid) || null }

function refreshInfo(kid) {
  const L = layers.get(kid)
  if (!S.layerInfo[kid]) S.layerInfo[kid] = { empty: true, rev: 0 }
  S.layerInfo[kid].rev++
  S.layerInfo[kid].empty = L ? R.isEmpty(L.img) : true
  S.historyRev++
}

function updateUnsaved() {
  S.unsavedStrokes = [...layers.values()].some((l) => l.dirty || l.timer)
}

function scheduleSave(kid) {
  const L = layers.get(kid)
  L.dirty = true
  clearTimeout(L.timer)
  L.timer = setTimeout(() => saveLayer(kid), AUTOSAVE_STROKES_MS)
  S.unsavedStrokes = true
}

function layerToBlob(img) {
  return new Promise((resolve, reject) => {
    const c = document.createElement('canvas')
    c.width = img.width; c.height = img.height
    c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(img.data), img.width, img.height), 0, 0)
    c.toBlob((b) => (b ? resolve(b) : reject(new Error('无法生成笔触图'))), 'image/png')
  })
}

export function saveLayer(kid) {
  const L = layers.get(kid)
  if (!L || !S.pid) return Promise.resolve()
  clearTimeout(L.timer)
  L.timer = null
  const pid = S.pid
  L.saving = L.saving.then(async () => {
    if (!L.dirty) return
    L.dirty = false
    try {
      await api.putStrokes(pid, kid, await layerToBlob(L.img))
    } catch (e) {
      L.dirty = true
      toast('笔触保存失败：' + errMsg(e), 'error')
    }
    updateUnsaved()
  })
  return L.saving
}

export async function flushStrokes() {
  await Promise.all([...layers.keys()].map((k) => saveLayer(k)))
  updateUnsaved()
  return !S.unsavedStrokes
}

async function loadLayerFromServer(pid, kid) {
  const res = await api.getStrokes(pid, kid)
  if (res.status === 204) return null
  const blob = await res.blob()
  const bmp = await createImageBitmap(blob, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' })
  const c = document.createElement('canvas')
  c.width = S.project.width; c.height = S.project.height
  const ctx = c.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(bmp, 0, 0)
  const d = ctx.getImageData(0, 0, c.width, c.height)
  return { width: d.width, height: d.height, data: d.data }
}

// 一次编辑 = begin → 修改 img → end（用差异包围盒生成撤销补丁）
// created：这次编辑是在预览帧上落笔、顺带新建了关键帧。若最后什么都没画上，或之后被撤销到空白，
// 就把这个关键帧一起去掉——不留下“误点一下”造成的空关键帧（空关键帧 = 这一刻特效消失）。
let op = null
export function opBegin(kid, created = false) {
  const L = getLayer(kid)
  op = { kid, before: R.cloneLayer(L.img), created }
}
export function opEnd() {
  if (!op) return
  const { kid, before, created } = op
  op = null
  const L = layers.get(kid)
  const box = R.diffBox(before, L.img)
  if (!box || (created && R.isEmpty(L.img))) {
    if (created) discardKeyframe(kid)
    return
  }
  L.undo.push({ box, before: R.cropPatch(before, box), after: R.cropPatch(L.img, box), created })
  if (L.undo.length > HISTORY_LIMIT) L.undo.shift()
  L.redo = []
  refreshInfo(kid)
  scheduleSave(kid)
}

export function canUndo() { void S.historyRev; const L = curKid.value && layers.get(curKid.value); return !!(L && L.undo.length) }
export function canRedo() { void S.historyRev; const L = curKid.value && layers.get(curKid.value); return !!(L && L.redo.length) }

export function undo() {
  const kid = curKid.value
  const L = kid && layers.get(kid)
  if (!L || !L.undo.length) return
  const e = L.undo.pop()
  R.applyPatch(L.img, e.before)
  if (e.created && R.isEmpty(L.img)) {           // 撤销掉了“落笔建帧”的那一笔：关键帧也一起撤掉
    discardKeyframe(kid)
    toast('已撤销，并移除了刚才落笔时新建的关键帧')
    return
  }
  L.redo.push(e)
  refreshInfo(kid)
  scheduleSave(kid)
}
export function redo() {
  const kid = curKid.value
  const L = kid && layers.get(kid)
  if (!L || !L.redo.length) return
  const e = L.redo.pop()
  R.applyPatch(L.img, e.after)
  L.undo.push(e)
  refreshInfo(kid)
  scheduleSave(kid)
}

export function clearCurrent() {
  const kid = curKid.value
  if (!kid) return
  opBegin(kid)
  R.clearLayer(getLayer(kid).img)
  opEnd()
}

/** 播放头前（prev）/后（next）最近的关键帧（播放头在关键帧上时即相邻关键帧）。 */
export function neighborOf(dir) {
  const list = resolved.value, f = S.playhead
  if (dir === 'prev') { for (let i = list.length - 1; i >= 0; i--) if (list[i].index < f) return list[i]; return null }
  return list.find((k) => k.index > f) || null
}

export async function copyFromNeighbor(dir) {
  const nb = neighborOf(dir)
  if (!nb) { toast(dir === 'prev' ? '前面没有关键帧了' : '后面没有关键帧了'); return }
  const src = layers.get(nb.id)
  if (!src || R.isEmpty(src.img)) { toast('相邻关键帧上没有笔触可复制'); return }
  const target = curKid.value ? { id: curKid.value, created: false } : ensureKeyframeAtPlayhead()
  if (!target) return
  if (!target.created && !isKfEmpty(target.id) && !(await confirmDialog('当前帧已有笔触，复制会替换它（可撤销）。继续吗？'))) return
  const kid = target.id
  opBegin(kid, target.created)
  getLayer(kid).img.data.set(src.img.data)
  opEnd()
}

// 吸管用：当前底图像素缓存
let basePix = { url: '', data: null }
export function loadBasePixels(url) {
  if (basePix.url === url && basePix.data) return Promise.resolve(basePix.data)
  return new Promise((resolve) => {
    const im = new Image()
    im.onload = () => {
      const c = document.createElement('canvas')
      c.width = im.naturalWidth; c.height = im.naturalHeight
      const ctx = c.getContext('2d', { willReadFrequently: true })
      ctx.drawImage(im, 0, 0)
      const d = ctx.getImageData(0, 0, c.width, c.height)
      basePix = { url, data: { width: d.width, height: d.height, data: d.data } }
      resolve(basePix.data)
    }
    im.onerror = () => resolve(null)
    im.src = url
  })
}

// 当前关键帧的真实底图（与生成用的完全相同）。图片参考/黑底时各帧底图都一样，固定用 0 号，切帧不闪。
export const baseUrl = computed(() => {
  const k = selectedKf.value
  if (!S.pid || !k) return ''
  return api.baseUrl(S.pid, livePreview.value || hasFrameRefs.value ? k.index : 0, S.baseRev)
})

// 画布上显示的底图：关键帧上 = 真实底图；拖动中或不在关键帧上 = 该帧的参考画面预览（视频）/ 同一张底图（图片、黑底）
export const previewFrame = computed(() => (S.scrub != null ? S.scrub : S.playhead))
export const isPreview = computed(() => S.scrubbing || S.scrub != null || !selectedKf.value)
export const canvasSrc = computed(() => {
  if (!S.pid || !S.project) return ''
  if (!isPreview.value) return baseUrl.value
  if (livePreview.value) return clipUrl(previewFrame.value)
  return api.baseUrl(S.pid, 0, S.baseRev)
})

// ---------------- 项目保存 ----------------
let lastSavedJson = ''
let lastBaseKey = ''
let projTimer = null
let projSaving = Promise.resolve()

function baseKey() {
  const p = S.project
  if (!p) return ''
  const r = p.reference
  const fr = p.frame_refs || {}
  return JSON.stringify([fr.first && fr.first.file + fr.first.original_name, fr.tail && fr.tail.file + fr.tail.original_name, r && r.file, r && r.original_name, r && r.start25, p.base_mode, p.blur_radius, p.blur_sigma, p.colors, p.width, p.height])
}

export function saveProject() {
  clearTimeout(projTimer)
  projTimer = null
  projSaving = projSaving.then(async () => {
    if (!S.project || !S.pid) return
    const json = JSON.stringify(S.project)
    if (json === lastSavedJson) { S.projectDirty = false; return }
    try {
      const r = await api.putProject(S.pid, JSON.parse(json))
      lastSavedJson = json
      S.videoWarning = r.video_warning || null
      const bk = baseKey()
      if (bk !== lastBaseKey) { lastBaseKey = bk; S.baseRev++ }
    } catch (e) {
      toast('项目保存失败：' + errMsg(e), 'error')
    }
    S.projectDirty = JSON.stringify(S.project) !== lastSavedJson
  })
  return projSaving
}

watch(() => (S.project ? JSON.stringify(S.project) : ''), (json) => {
  if (!json) return
  S.projectDirty = json !== lastSavedJson
  if (!S.projectDirty) return
  clearTimeout(projTimer)
  projTimer = setTimeout(saveProject, AUTOSAVE_PROJECT_MS)
})

export async function flushAll() {
  await saveProject()
  await flushStrokes()
  return !S.projectDirty && !S.unsavedStrokes
}

// ---------------- 打开 / 新建 / 另存 ----------------
export async function openProject(pid) {
  if (S.pid) await flushAll()
  const r = await api.getProject(pid)
  const p = r.project
  tlCache.clear()
  const tl = await fetchTimeline(Number(p.seconds))
  layers.clear()
  S.layerInfo = {}
  op = null
  S.pid = pid
  S.timeline = tl
  S.project = p
  lastSavedJson = JSON.stringify(p)
  lastBaseKey = baseKey()
  S.projectDirty = false
  S.videoWarning = r.video_warning || null
  S.baseRev++
  S.refRev++
  S.view = 'canvas'
  S.currentResult = null
  S.genJob = null
  S.promptNotice = ''
  S.promptWarnings = []
  S.playhead = 0
  S.scrub = null
  S.scrubbing = false
  S.clipStart = p.reference ? p.reference.start25 || 0 : 0
  try { localStorage.setItem('fx.lastPid', pid) } catch (_) { /* 忽略 */ }
  await Promise.all((r.strokes || []).map(async (kid) => {
    try {
      const img = await loadLayerFromServer(pid, kid)
      if (img) { const L = getLayer(kid); L.img = img; refreshInfo(kid) }
    } catch (e) { toast('读取笔触层失败：' + errMsg(e), 'error') }
  }))
  loadResults()
  if (!p.prompt.final) composeNow()
  adoptRunningJob()
}

export async function newProject(name) {
  const r = await api.createProject(name || '未命名项目')
  await openProject(r.id)
}

export async function saveAsCopy(name) {
  await flushAll()
  const r = await api.duplicate(S.pid, name)
  await openProject(r.id)
  toast('已另存为副本', 'ok')
}

export async function refreshProjectList() {
  S.projectList = await api.listProjects()
}

// ---------------- 关键帧 ----------------
const rid = () => {
  const cs = 'abcdefghijklmnopqrstuvwxyz0123456789'
  let s = ''
  for (let i = 0; i < 8; i++) s += cs[Math.floor(Math.random() * cs.length)]
  return 'k_' + s
}

export function selectKeyframe(kid) {
  const k = resolved.value.find((x) => x.id === kid)
  if (!k) return
  S.playhead = k.index
  getLayer(kid)
}

export function setPlayhead(f) {
  if (!S.timeline) return
  S.playhead = Math.max(0, Math.min(S.timeline.last, Math.round(f)))
}

const snapOn = () => S.project && S.project.snap !== false

/** 吸附开着时把播放头放回最近的网格点（松开拖动后调用：看到的帧 = 能放关键帧的帧）。 */
export function settlePlayhead() {
  if (S.timeline && snapOn()) S.playhead = snapTo(S.playhead, S.timeline.grid)
}

/** 方向键：吸附开 = 跳到上/下一个网格点；fine（Shift）或吸附关 = 逐帧。 */
export function stepPlayhead(dir, fine = false) {
  if (!S.timeline) return
  if (fine || !snapOn()) setPlayhead(S.playhead + dir)
  else S.playhead = stepOnGrid(S.playhead, dir, S.timeline.grid)
}

/** 跳到上/下一个关键帧。 */
export function jumpKeyframe(dir) {
  const nb = neighborOf(dir > 0 ? 'next' : 'prev')
  if (nb) S.playhead = nb.index
}

/** 在 frame（默认播放头）处确保有关键帧：吸附开时落到最近网格点。返回 {id, created}；播放头移到该帧。 */
export function ensureKeyframeAtPlayhead(frame = S.playhead) {
  const p = S.project, tl = S.timeline
  if (!p || !tl) return null
  let idx = Math.max(0, Math.min(tl.last, Math.round(frame)))
  if (snapOn()) idx = snapTo(idx, tl.grid)
  S.playhead = idx
  const ex = resolved.value.find((k) => k.index === idx)
  if (ex) { getLayer(ex.id); return { id: ex.id, created: false } }
  let kf
  if (idx === tl.last && !p.keyframes.some((k) => k.id === 'k_tail')) kf = { id: 'k_tail', index: -1, tail: true }
  else kf = { id: rid(), index: idx }
  p.keyframes.push(kf)
  p.scheme = 'custom'
  getLayer(kf.id)
  return { id: kf.id, created: true }
}

/** 静默移除关键帧（落笔建帧后什么都没画上 / 被撤销时用；不弹确认）。 */
function discardKeyframe(kid) {
  const p = S.project
  if (!p || kid === 'k_first') return
  p.keyframes = p.keyframes.filter((k) => k.id !== kid)
  dropKeyframes([kid])
}

function kfHasStrokes(kid) { return !isKfEmpty(kid) }

async function dropKeyframes(kids) {
  for (const kid of kids) {
    const L = layers.get(kid)
    if (L) { clearTimeout(L.timer); L.dirty = false }
    layers.delete(kid)
    delete S.layerInfo[kid]
    try { await api.delStrokes(S.pid, kid) } catch (_) { /* 文件可能本来就没有 */ }
  }
  updateUnsaved()
}

export async function applyScheme(n) {
  const p = S.project
  const tl = await fetchTimeline(Number(p.seconds), n)
  const target = tl.scheme_indices
  const cur = resolved.value
  const used = new Set()
  const next = []
  for (const idx of target) {
    const ex = cur.find((k) => k.index === idx && !used.has(k.id))
    if (ex) { used.add(ex.id); next.push(p.keyframes.find((k) => k.id === ex.id)); continue }
    if (idx === 0) next.push({ id: 'k_first', index: 0 })
    else if (idx === tl.last && !p.keyframes.some((k) => k.id === 'k_tail')) next.push({ id: 'k_tail', index: -1, tail: true })
    else next.push({ id: rid(), index: idx })
  }
  const keepIds = new Set(next.map((k) => k.id))
  const dropped = p.keyframes.filter((k) => !keepIds.has(k.id))
  const withStrokes = dropped.filter((k) => kfHasStrokes(k.id))
  if (withStrokes.length && !(await confirmDialog(
    `切换方案会丢掉 ${withStrokes.length} 个画了笔触的关键帧（同帧号的笔触会保留）。确定要切换吗？`, '丢弃并切换'))) return
  p.keyframes = next
  p.scheme = n
  await dropKeyframes(dropped.map((k) => k.id))
}

async function addMissingForScheme() {
  const p = S.project
  if (![0, 1, 2].includes(p.scheme)) return
  const tl = await fetchTimeline(Number(p.seconds), p.scheme)
  for (const idx of tl.scheme_indices) {
    if (resolved.value.some((k) => k.index === idx)) continue
    if (idx === tl.last && !p.keyframes.some((k) => k.id === 'k_tail')) p.keyframes.push({ id: 'k_tail', index: -1, tail: true })
    else p.keyframes.push({ id: rid(), index: idx })
  }
}

export async function setSeconds(n) {
  n = Math.max(1, Math.min(5, Math.round(n)))
  const p = S.project
  if (n === Number(p.seconds)) return
  const tl = await fetchTimeline(n)
  const drawnHiddenBefore = hiddenKfs.value.filter((k) => !isKfEmpty(k.id)).length
  p.seconds = n
  S.timeline = tl
  await addMissingForScheme()
  if (S.playhead > tl.last) S.playhead = tl.last
  settlePlayhead()
  const drawnHidden = hiddenKfs.value.filter((k) => !isKfEmpty(k.id)).length
  if (drawnHidden > drawnHiddenBefore) {
    toast(`有 ${drawnHidden} 个画了笔触的关键帧超出了 ${n} 秒，暂时不参与生成（时长改回去就会回来）`, 'info', 7000)
  }
}

/** “+ 加帧”/K 键/双击时间轴：在 frame（默认播放头）处新建关键帧。 */
export function addKeyframeAtPlayhead(frame = S.playhead) {
  const r = ensureKeyframeAtPlayhead(frame)
  if (r && !r.created) toast(`第 ${S.playhead} 帧已经是关键帧了，直接在画布上画即可`)
}

export function moveKeyframe(kid, raw) {
  const p = S.project, tl = S.timeline
  const kf = p.keyframes.find((k) => k.id === kid)
  if (!kf || kf.id === 'k_first' || kf.tail) return false
  let idx = Math.max(1, Math.min(tl.last - 1, Math.round(raw)))
  if (p.snap !== false) idx = snapTo(idx, tl.grid)
  if (idx <= 0 || idx >= tl.last) return false
  const cur = resolved.value.find((k) => k.id === kid)
  if (cur && cur.index === idx) return false
  if (resolved.value.some((k) => k.id !== kid && k.index === idx)) { toast(`第 ${idx} 帧已经有关键帧了`); return false }
  kf.index = idx
  p.scheme = 'custom'
  S.playhead = idx
  return true
}

export async function removeKeyframe(kid) {
  const p = S.project
  if (kid === 'k_first') { toast('首帧不能删除'); return }
  const kf = p.keyframes.find((k) => k.id === kid)
  if (!kf) return
  if (kfHasStrokes(kid) && !(await confirmDialog('这个关键帧上画了内容，删除后无法恢复。确定删除吗？', '删除'))) return
  p.keyframes = p.keyframes.filter((k) => k.id !== kid)
  p.scheme = 'custom'
  await dropKeyframes([kid])
}

/** 清理不参与生成的关键帧（超出时长或与别的帧重合）。 */
export async function removeHiddenKeyframes() {
  const list = hiddenKfs.value
  if (!list.length) return
  const drawn = list.filter((k) => !isKfEmpty(k.id)).length
  if (drawn && !(await confirmDialog(`其中 ${drawn} 个画了笔触，删除后无法恢复。确定删除这 ${list.length} 个不参与生成的关键帧吗？`, '删除'))) return
  const ids = new Set(list.map((k) => k.id))
  S.project.keyframes = S.project.keyframes.filter((k) => !ids.has(k.id))
  S.project.scheme = 'custom'
  await dropKeyframes([...ids])
}

export function setSnap(on) {
  const p = S.project
  p.snap = !!on
  if (on) {
    for (const kf of p.keyframes) {
      if (kf.tail || kf.id === 'k_first') continue
      const s = snapTo(kf.index, S.timeline.grid)
      if (s !== kf.index && !p.keyframes.some((o) => o !== kf && !o.tail && o.index === s)) kf.index = s
    }
    settlePlayhead()
    if (hiddenKfs.value.length) toast(`开启吸附后有 ${hiddenKfs.value.length} 个关键帧和别的帧落到了同一帧，暂时不参与生成（见时间轴上的提示）`, 'info', 7000)
  }
}

// ---------------- 尺寸 ----------------
export const snap64 = (v) => Math.max(256, Math.min(2048, Math.round(Number(v) / 64) * 64))

export async function changeSize(w, h) {
  const p = S.project
  w = snap64(w); h = snap64(h)
  if (w === p.width && h === p.height) return
  const withContent = [...layers.entries()].filter(([, L]) => !R.isEmpty(L.img))
  if (withContent.length && !(await confirmDialog(
    `把输出尺寸改为 ${w}×${h} 后，已画的 ${withContent.length} 张笔触层会按最近邻缩放到新尺寸（画布比例不同会变形）。继续吗？`, '改尺寸'))) return
  await flushAll()
  const ow = p.width, oh = p.height
  p.width = w; p.height = h
  await saveProject()
  if (S.projectDirty) { p.width = ow; p.height = oh; return }
  for (const [kid, L] of layers.entries()) {
    L.img = R.resizeNearest(L.img, w, h)
    L.undo = []; L.redo = []
    refreshInfo(kid)
    if (S.layerInfo[kid].empty) { L.dirty = false } else { L.dirty = true; saveLayer(kid) }
  }
  basePix = { url: '', data: null }
  toast(`输出尺寸已改为 ${w}×${h}`, 'ok')
}

// ---------------- 参考画面 ----------------
export async function uploadReference(file) {
  try {
    await saveProject()
    const info = await api.uploadReference(S.pid, file)
    S.project.reference = info
    S.clipStart = info.start25 || 0
    lastBaseKey = baseKey()
    S.baseRev++
    S.refRev++
    const r = await api.getProject(S.pid)
    S.videoWarning = r.video_warning || null
    toast('参考画面已载入', 'ok')
    // 输出比例跟素材走（不裁切）；面积按显存预算，后端给出建议尺寸
    if (info.fit_size) await changeSize(info.fit_size[0], info.fit_size[1])
  } catch (e) {
    toast('上传失败：' + errMsg(e), 'error')
  }
}

// 首帧 / 尾帧图片：只管这一帧的底图，不影响主参考
export async function uploadFrameRef(slot, file) {
  try {
    await saveProject()
    const info = await api.uploadFrameRef(S.pid, slot, file)
    if (!S.project.frame_refs) S.project.frame_refs = {}
    S.project.frame_refs[slot] = info
    lastBaseKey = baseKey()
    S.baseRev++
    S.refRev++
    toast(slot === 'first' ? '首帧图已载入' : '尾帧图已载入', 'ok')
    // 还没有主参考时，输出比例跟这张图走（不裁切）
    if (!S.project.reference && info.fit_size) await changeSize(info.fit_size[0], info.fit_size[1])
  } catch (e) {
    toast('上传失败：' + errMsg(e), 'error')
  }
}

export async function removeFrameRef(slot) {
  try {
    await api.deleteFrameRef(S.pid, slot)
    if (S.project.frame_refs) delete S.project.frame_refs[slot]
    lastBaseKey = baseKey()
    S.baseRev++
    S.refRev++
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

export async function removeReference() {
  try {
    await api.deleteReference(S.pid)
    S.project.reference = null
    lastBaseKey = baseKey()
    S.baseRev++
    S.refRev++
    S.videoWarning = null
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

// ---------------- 提示词 ----------------
let composeTimer = null
let composeSeq = 0
export async function composeNow(force = false) {
  const p = S.project
  if (!p) return null
  const pr = p.prompt
  if (pr.final_edited && !force) return null
  const seq = ++composeSeq
  try {
    const r = await api.compose({
      scene_en: pr.scene_en, effect: pr.effect, effect_desc_en: pr.effect_desc_en,
      camera: pr.camera, nothing_else: pr.nothing_else,
    }, p.base_mode)
    if (seq === composeSeq && (!pr.final_edited || force)) {
      pr.final = r.final
      if (force) pr.final_edited = false
    }
    return r
  } catch (e) {
    toast('拼接提示词失败：' + errMsg(e), 'error')
    return null
  }
}

watch(() => {
  const p = S.project
  if (!p) return ''
  const pr = p.prompt
  return JSON.stringify([pr.scene_en, pr.effect, pr.effect_desc_en, pr.camera, pr.nothing_else, p.base_mode, pr.final_edited])
}, () => {
  if (!S.project || S.project.prompt.final_edited) return
  clearTimeout(composeTimer)
  composeTimer = setTimeout(() => composeNow(), 300)
})

export async function translateText(text) {
  const r = await api.translate(text)
  if (r.job == null) return r.result || { english: '' }
  const job = await waitJob(r.job)
  if (job.state === 'error') throw new Error(job.error || '翻译失败')
  if (job.state === 'cancelled') throw new Error('翻译已取消')
  return job.result || { english: '' }
}

// 点“转英文”：field = 'scene' | 'effect_desc'，把中文译到对应英文框
export async function translateField(field) {
  const pr = S.project.prompt
  const text = (pr[field] || '').trim()
  if (!text) { toast('先在左边写点中文再转英文'); return }
  S.translating[field] = true
  try {
    const r = await translateText(text)
    pr[field + '_en'] = r.english || ''
    if (r.warning) S.promptWarnings = [...S.promptWarnings.filter((w) => w.field !== field), { field, text: r.warning }]
    else S.promptWarnings = S.promptWarnings.filter((w) => w.field !== field)
  } catch (e) {
    toast('翻译失败：' + errMsg(e), 'error')
  } finally {
    S.translating[field] = false
  }
}

// 生成前：把任何含中文的字段转成英文并填进可见的英文框。返回 true 表示做了转换或被拦住（需用户确认后再点生成）
async function ensureEnglish() {
  const p = S.project, pr = p.prompt
  let did = false
  S.promptWarnings = []
  const warn = (field, r) => { if (r.warning) S.promptWarnings.push({ field, text: r.warning }) }
  const pairs = [['scene', 'scene_en', p.base_mode !== 0], ['effect_desc', 'effect_desc_en', true]]
  for (const [zh, en, use] of pairs) {
    if (!use) continue
    const z = (pr[zh] || '').trim()
    if (z && hasChinese(z)) {
      if (!(pr[en] || '').trim() || hasChinese(pr[en])) {
        const r = await translateText(z); pr[en] = r.english || ''; warn(zh, r); did = true
      }
    } else if (z && !(pr[en] || '').trim()) {
      pr[en] = z // 本来就是英文，直接放进英文框
    } else if (hasChinese(pr[en])) {
      const r = await translateText(pr[en]); pr[en] = r.english || ''; warn(zh, r); did = true
    }
  }
  if (hasChinese(pr.camera)) {
    const r = await translateText(pr.camera); pr.camera = r.english || ''; warn('camera', r); did = true
  }
  if (!pr.final_edited) {
    await composeNow()
  } else if (hasChinese(pr.final)) {
    const r = await translateText(pr.final); pr.final = r.english || ''; warn('final', r); did = true
  }
  if (hasChinese(pr.final)) {
    S.promptNotice = '英文提示词里还有中文，请在右侧手动改成英文后再点生成'
    return true
  }
  if (did) {
    S.promptNotice = '已转成英文，请确认后再点生成'
    return true
  }
  S.promptNotice = ''
  return false
}

// ---------------- 任务（WebSocket + 轮询） ----------------
const jobCache = new Map()
const waiters = {}
const lastSeen = {}
const handled = new Set()

function waitJob(id) {
  return new Promise((resolve) => {
    const c = jobCache.get(id)
    if (c && TERMINAL.includes(c.state)) return resolve(c)
    ;(waiters[id] ||= []).push(resolve)
    api.getJob(id).then(onJob).catch(() => {})
  })
}

function onJob(job) {
  if (!job || !job.id) return
  lastSeen[job.id] = Date.now()
  const prev = jobCache.get(job.id)
  if (prev && prev.version > job.version) return
  jobCache.set(job.id, job)
  if (S.genJob && S.genJob.id === job.id) {
    S.genJob = job
    if (TERMINAL.includes(job.state) && !handled.has(job.id)) {
      handled.add(job.id)
      onGenerateFinished(job)
    }
  }
  if (TERMINAL.includes(job.state) && waiters[job.id]) {
    for (const f of waiters[job.id]) f(job)
    delete waiters[job.id]
  }
}

async function onGenerateFinished(job) {
  if (job.state === 'done' && job.result) {
    await loadResults()
    const hit = S.results.find((r) => r.file === job.result.file)
    S.currentResult = hit || { file: job.result.file, params: job.result.params, composites: {} }
    S.view = 'result'
    toast('生成完成', 'ok')
  } else if (job.state === 'error') {
    toast(job.error || '生成失败', 'error', 9000)
  } else if (job.state === 'cancelled') {
    toast('已取消生成')
  }
}

export async function loadResults() {
  if (!S.pid) return
  try { S.results = await api.results(S.pid) } catch (_) { S.results = [] }
}

function adoptRunningJob() {
  if (S.genJob) return
  const q = (S.status.queue || []).find((j) => j.kind === 'generate' && j.project === S.pid)
  if (q) { S.genJob = q; jobCache.set(q.id, q) }
}

function onStatus(st) {
  S.status = st
  if (S.pid) adoptRunningJob()
}

let ws = null
let wsDelay = 500
export function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  try { ws = new WebSocket(`${proto}://${location.host}/api/ws`) } catch (_) { setTimeout(connectWs, 2000); return }
  ws.onopen = () => { S.wsOk = true; wsDelay = 500 }
  ws.onmessage = (ev) => {
    try {
      const m = JSON.parse(ev.data)
      if (m.type === 'status') onStatus(m.data)
      else if (m.type === 'job') onJob(m.data)
    } catch (_) { /* 忽略坏消息 */ }
  }
  ws.onclose = () => {
    S.wsOk = false
    setTimeout(connectWs, wsDelay)
    wsDelay = Math.min(wsDelay * 2, 8000)
  }
  ws.onerror = () => { try { ws.close() } catch (_) { /* 忽略 */ } }
}

let pollTimer = null
function startPolling() {
  if (pollTimer) return
  let n = 0
  pollTimer = setInterval(async () => {
    n++
    if (!S.wsOk && n % 3 === 0) {
      try { onStatus(await api.status()) } catch (_) { /* 后端暂时连不上 */ }
    }
    const ids = new Set(Object.keys(waiters))
    if (S.genJob && !TERMINAL.includes(S.genJob.state)) ids.add(S.genJob.id)
    for (const id of ids) {
      if (!S.wsOk || Date.now() - (lastSeen[id] || 0) > 6000) {
        try { onJob(await api.getJob(id)) } catch (_) { /* 下次再试 */ }
      }
    }
  }, 1500)
}

// ---------------- 生成 ----------------
export async function startGenerate() {
  if (S.genBusy || !S.project) return
  if (S.genJob && !TERMINAL.includes(S.genJob.state)) { toast('已经有一个生成任务在进行'); return }
  S.genBusy = true
  S.promptNotice = ''
  try {
    await flushAll()
    if (S.projectDirty || S.unsavedStrokes) { toast('项目还没保存成功，请稍后重试', 'error'); return }
    if (await ensureEnglish()) { S.view = 'canvas'; return }
    // ensureEnglish 可能刚改了英文框和最终提示词（例如把描述框里的英文搬进英文框并重新拼接）；
    // 后台从磁盘读项目，所以提交前必须再存一次，否则会用旧提示词生成
    await flushAll()
    if (S.projectDirty || S.unsavedStrokes) { toast('项目还没保存成功，请稍后重试', 'error'); return }
    if (!(await confirmEmptyKeyframes())) return
    const r = await api.generate(S.pid)
    S.genJob = { id: r.job, state: 'queued', stage: '排队中', progress: 0, step: null, message: '', notes: [], error: null, version: -1 }
    handled.delete(r.job)
    api.getJob(r.job).then(onJob).catch(() => {})
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    S.genBusy = false
  }
}

// 没画的关键帧 = 这一刻没有特效（特效会在这里消失）。容易是误操作，生成前提醒一次；可按项目关掉。
async function confirmEmptyKeyframes() {
  const p = S.project
  const empty = emptyKfs.value
  if (!empty.length || p.skip_empty_warning) return true
  const all = empty.length === resolved.value.length
  const list = empty.map((k) => (k.index === 0 ? '首帧' : k.tail ? `尾帧（第 ${k.index} 帧）` : `第 ${k.index} 帧`)).join('、')
  const msg = all
    ? '所有关键帧都还没画，生成出来不会有特效。确定要生成吗？'
    : `这些关键帧没画：${list}。
没画 = 这一刻没有特效（特效会在这里消失或还没出现）。如果不是有意留空，请先画上或删掉这些关键帧。`
  const r = await confirmDialog(msg, '照样生成', '有关键帧没画', all ? null : '这是有意留空的，本项目不再提醒')
  const ok = r && typeof r === 'object' ? r.ok : r
  if (!ok) return false
  if (r && r.checked) { p.skip_empty_warning = true; await flushAll() }
  return true
}

export async function cancelGenerate() {
  if (!S.genJob) return
  try { onJob(await api.cancelJob(S.genJob.id)) } catch (e) { toast(errMsg(e), 'error') }
}

export function dismissJob() {
  if (S.genJob && TERMINAL.includes(S.genJob.state)) S.genJob = null
}
export const genActive = computed(() => !!S.genJob && !TERMINAL.includes(S.genJob.state))

// ---------------- 启动 ----------------
export async function boot() {
  startPolling()
  connectWs()
  api.meta().then((m) => { S.meta = m }).catch((e) => toast('读取配置失败：' + errMsg(e), 'error'))
  api.status().then(onStatus).catch(() => {})
  loadSelfcheck()
  api.lan().then((r) => { S.lan = r }).catch(() => {})
  let pid = null
  try { pid = localStorage.getItem('fx.lastPid') } catch (_) { /* 忽略 */ }
  try {
    if (pid) { try { await openProject(pid) } catch (_) { pid = null } }
    if (!pid) {
      const list = await api.listProjects()
      if (list.length) await openProject(list[0].id)
      else await newProject('未命名项目')
    }
  } catch (e) {
    toast('打开项目失败：' + errMsg(e), 'error')
  }
  S.ready = true
}

// ---------------- 删除 / 引擎 ----------------
export async function deleteProject(pid, name) {
  if (!(await confirmDialog(`删除项目「${name}」？项目和它的全部成片会移到软件目录的 runtime\\trash 里（30 天后自动清除，期间可手动找回）。`, '删除'))) return false
  if (pid === S.pid) await flushAll()
  try {
    await api.deleteProject(pid)
  } catch (e) { toast('删除失败：' + errMsg(e), 'error'); return false }
  toast('项目已移到回收站', 'ok')
  if (pid === S.pid) {
    S.pid = null
    try { localStorage.removeItem('fx.lastPid') } catch (_) { /* 忽略 */ }
    const list = await api.listProjects()
    if (list.length) await openProject(list[0].id)
    else await newProject('未命名项目')
  }
  await refreshProjectList()
  return true
}

export async function deleteResult(r) {
  if (!(await confirmDialog('删除这次生成的结果？（连同导出的合成版一起移到 runtime\\trash，30 天内可手动找回）', '删除'))) return
  try { await api.deleteResult(r.file) } catch (e) { toast('删除失败：' + errMsg(e), 'error'); return }
  if (S.currentResult && S.currentResult.file === r.file) S.currentResult = null
  await loadResults()
  if (!S.currentResult && S.results.length) S.currentResult = S.results[0]
  if (!S.results.length) S.view = 'canvas'
}

export async function restartEngine() {
  try { await api.engineRestart(); toast('正在重启引擎…') } catch (e) { toast(errMsg(e), 'error') }
}

export async function freeVram() {
  try { await api.engineFree(); toast('已释放显存。下次生成会重新加载模型（多等 1–2 分钟）', 'ok', 6000) } catch (e) { toast(errMsg(e), 'error') }
}

export async function loadSelfcheck() {
  try { S.selfcheck = await api.selfcheck() } catch (e) { S.selfcheck = null }
}
