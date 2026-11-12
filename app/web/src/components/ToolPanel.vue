<script setup>
import { computed } from 'vue'
import { S, undo, redo, canUndo, canRedo, clearCurrent, copyFromNeighbor, neighborOf, confirmDialog, isKfEmpty, curKid } from '../store'
import ColorPicker from './ColorPicker.vue'
import { hexToRgb } from '../lib/raster'

const tools = [
  { id: 'brush', name: '画笔', key: 'B', icon: '✎' },
  { id: 'eraser', name: '橡皮', key: 'E', icon: '⌫' },
  { id: 'fill', name: '填充', key: 'G', icon: '▣' },
  { id: 'eyedrop', name: '吸管', key: 'I', icon: '◉' },
]
const hasPrev = computed(() => { void S.playhead; return !!neighborOf('prev') })
const hasNext = computed(() => { void S.playhead; return !!neighborOf('next') })
const curEmpty = computed(() => !curKid.value || isKfEmpty(curKid.value))

async function onClear() {
  if (curEmpty.value) return
  if (await confirmDialog('清除当前关键帧上的全部笔触？（可以用撤销找回）', '清除')) clearCurrent()
}

function addPalette() {
  const pal = S.project.palette
  if (pal.some((c) => c.color.toLowerCase() === S.color.toLowerCase())) return
  pal.push({ name: '自定义色 ' + (pal.length + 1), color: S.color })
}
function delPalette(i) { S.project.palette.splice(i, 1) }
function rename(i, e) {
  const v = e.target.value.trim()
  S.project.palette[i].name = v || S.project.palette[i].name
  e.target.value = S.project.palette[i].name
}
function pick(c) { S.color = c.color; if (S.tool === 'eraser' || S.tool === 'eyedrop') S.tool = 'brush' }
function editName(i) {
  const el = document.getElementById('pal-name-' + i)
  if (el) { el.disabled = false; el.focus(); el.select() }
}
function lockName(i, e) { rename(i, e); e.target.disabled = true }
void hexToRgb
</script>

<template>
  <aside class="tools">
    <div class="sec">
      <div class="grid4">
        <button v-for="t in tools" :key="t.id" class="tool" :class="{ on: S.tool === t.id }" @click="S.tool = t.id" :title="`${t.name}（${t.key}）`">
          <span class="ic">{{ t.icon }}</span><span>{{ t.name }}</span>
        </button>
      </div>
      <div class="field">
        <span class="lbl">笔刷大小 {{ S.size }} px（[ ] 调整）</span>
        <div class="row"><input class="grow" type="range" min="1" max="120" v-model.number="S.size" />
          <input type="number" min="1" max="200" v-model.number="S.size" style="width:54px" /></div>
      </div>
      <label class="row"><input type="checkbox" v-model="S.soft" /> 柔边笔刷（高级，默认关）</label>
      <div class="hint" v-if="!S.soft">硬边·不透明·纯色：画出来的颜色就是选中的颜色。</div>
    </div>

    <div class="sec">
      <div class="row wrap">
        <button :disabled="!canUndo()" @click="undo" title="Ctrl+Z">↶ 撤销</button>
        <button :disabled="!canRedo()" @click="redo" title="Ctrl+Y">↷ 重做</button>
        <button class="danger" @click="onClear" :disabled="curEmpty">清除当前帧</button>
      </div>
      <div class="row wrap">
        <button :disabled="!hasPrev" @click="copyFromNeighbor('prev')" title="把前一个关键帧的笔触复制到这里（不在关键帧上时会在这里新建关键帧）">复制前一关键帧</button>
        <button :disabled="!hasNext" @click="copyFromNeighbor('next')">复制后一关键帧</button>
      </div>
    </div>

    <div class="sec">
      <label class="row"><input type="checkbox" v-model="S.onionOn" /> 前一关键帧笔触叠影（30%）</label>
      <div class="field">
        <span class="lbl">底图透明度（仅显示辅助）{{ Math.round(S.baseOpacity * 100) }}%</span>
        <input type="range" min="0" max="1" step="0.05" v-model.number="S.baseOpacity" style="width:100%" />
      </div>
      <div class="hint">叠影和透明度只影响屏幕显示，不会进入保存或生成的笔触层。</div>
    </div>

    <div class="sec">
      <ColorPicker />
    </div>

    <div class="sec">
      <div class="row"><b class="grow">预设色板</b><button class="small" @click="addPalette">+ 添加当前色</button></div>
      <div class="pal">
        <div v-for="(c, i) in S.project.palette" :key="i" class="pc" :class="{ cur: c.color.toLowerCase() === S.color.toLowerCase() }">
          <button class="sw" :style="{ background: c.color }" :title="c.color" @click="pick(c)"></button>
          <input :id="'pal-name-' + i" class="pn" type="text" :value="c.name" disabled @blur="lockName(i, $event)" @keydown.enter="$event.target.blur()" />
          <button class="small x" title="改名" @click="editName(i)">✎</button>
          <button class="small x danger" title="删除" @click="delPalette(i)">×</button>
        </div>
        <div v-if="!S.project.palette.length" class="dim">色板是空的</div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.tools { background: var(--bg2); border-right: 1px solid var(--line); overflow-y: auto; min-height: 0; }
.sec { padding: 10px 12px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; }
.grid4 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.tool { display: flex; align-items: center; gap: 6px; justify-content: center; padding: 7px 4px; }
.ic { font-size: 16px; }
.pal { display: flex; flex-direction: column; gap: 3px; }
.pc { display: flex; align-items: center; gap: 4px; padding: 1px; border-radius: 4px; }
.pc.cur { background: #2a2f3a; outline: 1px solid var(--accent); }
.sw { width: 26px; height: 22px; padding: 0; border-radius: 4px; border: 1px solid #000; flex: none; }
.pn { flex: 1; min-width: 0; border: 1px solid transparent; background: transparent; padding: 1px 3px; font-size: 12px; text-overflow: ellipsis; }
.pn:disabled { opacity: 1; color: var(--text); }
.pn:not(:disabled) { background: var(--bg); border-color: var(--blue); }
.x { padding: 0 5px; line-height: 18px; }
</style>
