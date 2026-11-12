<script setup>
import { computed, ref, watch } from 'vue'
import { S, setSeconds, changeSize, snap64 } from '../store'

const adv = ref(false)
const presets = computed(() => (S.meta ? S.meta.size_presets : []))
const wIn = ref(S.project.width)
const hIn = ref(S.project.height)
watch(() => [S.project.width, S.project.height], ([w, h]) => { wIn.value = w; hIn.value = h })

const presetValue = computed(() => {
  const p = presets.value.find((x) => x.w === S.project.width && x.h === S.project.height)
  return p ? `${p.w}x${p.h}` : 'custom'
})
function onPreset(e) {
  if (e.target.value === 'custom') return
  const [w, h] = e.target.value.split('x').map(Number)
  changeSize(w, h)
}
function applySize() {
  const w = snap64(wIn.value), h = snap64(hIn.value)
  wIn.value = w; hIn.value = h
  changeSize(w, h)
}
function fixSeed() { const v = Math.floor(Number(S.project.seed)); S.project.seed = Number.isFinite(v) && v >= 0 ? v : 0 }
function randSeed() { S.project.seed = Math.floor(Math.random() * 2147483647) }
const frames = computed(() => 24 * S.project.seconds + 1)
</script>

<template>
  <div class="sp">
    <div class="field">
      <span class="lbl">时长：{{ S.project.seconds }} 秒（{{ frames }} 帧，25fps）</span>
      <div class="row">
        <button v-for="n in 5" :key="n" class="grow" :class="{ on: S.project.seconds === n }" @click="setSeconds(n)">{{ n }} 秒</button>
      </div>
    </div>

    <div class="field">
      <span class="lbl">输出尺寸</span>
      <select :value="presetValue" @change="onPreset" style="width:100%">
        <option v-for="p in presets" :key="p.label" :value="`${p.w}x${p.h}`">{{ p.label }}</option>
        <option value="custom">自定义</option>
      </select>
      <div class="row" style="margin-top:5px">
        <input type="number" v-model.number="wIn" step="64" min="256" max="2048" style="width:78px" @change="applySize" />
        <span>×</span>
        <input type="number" v-model.number="hIn" step="64" min="256" max="2048" style="width:78px" @change="applySize" />
        <span class="hint">自动吸附到 64 的倍数</span>
      </div>
      <div class="hint">改尺寸会把已画的笔触层按最近邻缩放到新尺寸。尺寸越大越吃显存。</div>
    </div>

    <div class="field">
      <span class="lbl">seed（相同设置 + 相同 seed = 相同结果）</span>
      <div class="row">
        <input type="number" class="grow" v-model.number="S.project.seed" min="0" step="1" @change="fixSeed" />
        <button @click="randSeed">🎲 随机</button>
      </div>
    </div>

    <div class="field">
      <div class="row" style="cursor:pointer" @click="adv = !adv"><span>{{ adv ? '▾' : '▸' }}</span><b>高级</b></div>
      <div v-show="adv" class="advbox">
        <div class="row"><span class="lbl2">LoRA 强度 {{ Number(S.project.lora_strength).toFixed(2) }}</span>
          <input class="grow" type="range" min="0" max="1.5" step="0.05" v-model.number="S.project.lora_strength" />
          <input type="number" min="0" max="1.5" step="0.05" v-model.number="S.project.lora_strength" style="width:60px" /></div>
        <div class="row"><span class="lbl2">解码分块</span>
          <select v-model.number="S.project.tile_size">
            <option :value="512">512（默认）</option>
            <option :value="256">256（更省显存、更慢）</option>
          </select></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sp { display: flex; flex-direction: column; gap: 10px; }
.advbox { display: flex; flex-direction: column; gap: 8px; margin-top: 6px; }
.lbl2 { width: 112px; font-size: 12px; color: var(--dim); }
</style>
