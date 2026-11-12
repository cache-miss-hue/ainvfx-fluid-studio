<script setup>
// 自绘取色器：HSV 方块（饱和度×明度）+ 色相条 + 十六进制输入。
import { ref, watch, onMounted } from 'vue'
import { S } from '../store'
import { hexToRgb, rgbToHex, rgbToHsv, hsvToRgb } from '../lib/raster'

const SV_W = 200, SV_H = 130
const svCanvas = ref(null)
const hueCanvas = ref(null)
const hex = ref(S.color)
const hsv = ref(rgbToHsv(...(hexToRgb(S.color) || [255, 120, 20])))

function drawSV() {
  const c = svCanvas.value
  if (!c) return
  const ctx = c.getContext('2d')
  const img = ctx.createImageData(SV_W, SV_H)
  const h = hsv.value[0]
  for (let y = 0; y < SV_H; y++) {
    for (let x = 0; x < SV_W; x++) {
      const [r, g, b] = hsvToRgb(h, x / (SV_W - 1), 1 - y / (SV_H - 1))
      const i = (y * SV_W + x) * 4
      img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
}
function drawHue() {
  const c = hueCanvas.value
  const ctx = c.getContext('2d')
  const img = ctx.createImageData(SV_W, 14)
  for (let x = 0; x < SV_W; x++) {
    const [r, g, b] = hsvToRgb((x / (SV_W - 1)) * 360, 1, 1)
    for (let y = 0; y < 14; y++) {
      const i = (y * SV_W + x) * 4
      img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
}
onMounted(() => { drawHue(); drawSV() })

let fromSelf = false
function commit() {
  const [r, g, b] = hsvToRgb(...hsv.value)
  fromSelf = true
  S.color = rgbToHex(r, g, b)
  hex.value = S.color
  if (S.tool === 'eraser' || S.tool === 'eyedrop') S.tool = 'brush'
}
watch(() => S.color, (c) => {
  hex.value = c
  if (fromSelf) { fromSelf = false; return }
  const rgb = hexToRgb(c)
  if (!rgb) return
  const n = rgbToHsv(...rgb)
  // 灰色/黑色时保留原色相，避免滑块乱跳
  if (n[1] === 0 || n[2] === 0) n[0] = hsv.value[0]
  hsv.value = n
  drawSV()
})
watch(() => hsv.value[0], drawSV)

function drag(e, handler) {
  e.preventDefault()
  const el = e.currentTarget
  el.setPointerCapture(e.pointerId)
  handler(e)
  const mv = (ev) => handler(ev)
  const up = () => { el.removeEventListener('pointermove', mv); el.removeEventListener('pointerup', up) }
  el.addEventListener('pointermove', mv)
  el.addEventListener('pointerup', up)
}
function onSV(e) {
  const r = svCanvas.value.getBoundingClientRect()
  const s = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
  const v = 1 - Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))
  hsv.value = [hsv.value[0], s, v]
  commit()
}
function onHue(e) {
  const r = hueCanvas.value.getBoundingClientRect()
  hsv.value = [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * 359.99, hsv.value[1] || 1, hsv.value[2] || 1]
  commit()
}
function onHex() {
  const rgb = hexToRgb(hex.value)
  if (!rgb) { hex.value = S.color; return }
  S.color = rgbToHex(...rgb)
}
</script>

<template>
  <div class="cp">
    <div class="svwrap" @pointerdown="drag($event, onSV)">
      <canvas ref="svCanvas" :width="SV_W" :height="SV_H" class="sv"></canvas>
      <i class="mk" :style="{ left: hsv[1] * 100 + '%', top: (1 - hsv[2]) * 100 + '%' }"></i>
    </div>
    <div class="huewrap" @pointerdown="drag($event, onHue)">
      <canvas ref="hueCanvas" :width="SV_W" :height="14" class="hue"></canvas>
      <i class="hk" :style="{ left: (hsv[0] / 360) * 100 + '%' }"></i>
    </div>
    <div class="row">
      <span class="cur" :style="{ background: S.color }"></span>
      <input type="text" class="grow" v-model="hex" maxlength="7" spellcheck="false" @change="onHex" @keydown.enter="onHex" />
      <button :class="{ on: S.tool === 'eyedrop' }" @click="S.tool = 'eyedrop'" title="吸管（I）：从底图+笔触的合成画面取色，画笔时按住 Alt 点击也可取色">吸管</button>
    </div>
  </div>
</template>

<style scoped>
.cp { display: flex; flex-direction: column; gap: 8px; }
.svwrap, .huewrap { position: relative; cursor: crosshair; touch-action: none; line-height: 0; }
.sv { width: 100%; height: 130px; border-radius: 4px; border: 1px solid #000; }
.hue { width: 100%; height: 14px; border-radius: 4px; border: 1px solid #000; }
.mk { position: absolute; width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px #000; transform: translate(-50%, -50%); pointer-events: none; }
.hk { position: absolute; top: -2px; width: 6px; height: 18px; border: 2px solid #fff; box-shadow: 0 0 0 1px #000; border-radius: 2px; transform: translateX(-50%); pointer-events: none; }
.cur { width: 32px; height: 28px; border-radius: 5px; border: 1px solid #000; flex: none; }
</style>
