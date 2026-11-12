<script setup>
import { reactive } from 'vue'
import RefPanel from './RefPanel.vue'
import PromptPanel from './PromptPanel.vue'
import SizePanel from './SizePanel.vue'

const open = reactive({ ref: true, prompt: true, size: true })
</script>

<template>
  <aside class="right">
    <div class="card">
      <div class="card-h" @click="open.ref = !open.ref"><span>{{ open.ref ? '▾' : '▸' }}</span> ① 参考 / 底图</div>
      <div class="card-b" v-show="open.ref"><RefPanel /></div>
    </div>
    <div class="card">
      <div class="card-h" @click="open.prompt = !open.prompt"><span>{{ open.prompt ? '▾' : '▸' }}</span> ② 提示词</div>
      <div class="card-b" v-show="open.prompt"><PromptPanel /></div>
    </div>
    <div class="card">
      <div class="card-h" @click="open.size = !open.size"><span>{{ open.size ? '▾' : '▸' }}</span> ③ 尺寸 / seed / 时长</div>
      <div class="card-b" v-show="open.size"><SizePanel /></div>
    </div>
  </aside>
</template>

<style scoped>
.right { background: var(--bg2); border-left: 1px solid var(--line); overflow-y: auto; min-height: 0; }
</style>
