<script setup>
import { computed } from 'vue'
import { S, translateField, composeNow, hasChinese } from '../store'

const pr = computed(() => S.project.prompt)
const blackMode = computed(() => S.project.base_mode === 0)
const effects = computed(() => (S.meta ? S.meta.effects : []))
const curEffect = computed(() => effects.value.find((e) => e.id === pr.value.effect))

function onFinalInput(e) {
  pr.value.final = e.target.value
  pr.value.final_edited = true
}
function warnFor(f) { return S.promptWarnings.filter((w) => w.field === f) }
const finalChinese = computed(() => hasChinese(pr.value.final))
</script>

<template>
  <div class="pp">
    <div v-if="S.promptNotice" class="notice">{{ S.promptNotice }}</div>

    <div class="field">
      <span class="lbl">画面主体与场景（中文）</span>
      <textarea rows="2" v-model="pr.scene" :disabled="blackMode" placeholder="例如：一辆停在废墟街道上的坦克"></textarea>
      <div v-if="blackMode" class="hint">黑底模式只写特效，不描述场景。</div>
      <div class="row">
        <button class="small" :disabled="blackMode || !pr.scene.trim() || S.translating.scene" @click="translateField('scene')">
          {{ S.translating.scene ? '翻译中…' : '转英文 ↓' }}</button>
        <span class="dim" style="font-size:12px">English</span>
      </div>
      <textarea rows="2" v-model="pr.scene_en" :disabled="blackMode" placeholder="scene in English"></textarea>
      <div v-for="(w, i) in warnFor('scene')" :key="i" class="warnbox">{{ w.text }}</div>
    </div>

    <div class="field">
      <span class="lbl">特效类型</span>
      <select v-model="pr.effect" style="width:100%">
        <option v-for="e in effects" :key="e.id" :value="e.id">{{ e.zh }}</option>
      </select>
      <div v-if="curEffect && curEffect.en" class="hint">内置短语：{{ curEffect.en }}</div>
    </div>

    <div class="field">
      <span class="lbl">特效描述（可选，写了就覆盖上面的内置短语）</span>
      <textarea rows="2" v-model="pr.effect_desc" placeholder="例如：橙红色火球从炮口喷出，黑烟向上翻滚"></textarea>
      <div class="row">
        <button class="small" :disabled="!pr.effect_desc.trim() || S.translating.effect_desc" @click="translateField('effect_desc')">
          {{ S.translating.effect_desc ? '翻译中…' : '转英文 ↓' }}</button>
        <span class="dim" style="font-size:12px">English</span>
      </div>
      <textarea rows="2" v-model="pr.effect_desc_en" placeholder="effect description in English"></textarea>
      <div v-for="(w, i) in warnFor('effect_desc')" :key="i" class="warnbox">{{ w.text }}</div>
    </div>

    <div class="field">
      <span class="lbl">镜头</span>
      <input type="text" v-model="pr.camera" style="width:100%" placeholder="static camera" />
    </div>
    <label class="row"><input type="checkbox" v-model="pr.nothing_else" /> 加上 “nothing else in sight”（画面里不要别的东西）</label>

    <div class="field">
      <div class="row">
        <span class="lbl grow">英文最终提示词{{ pr.final_edited ? '（已手动修改，不再自动更新）' : '（自动拼接）' }}</span>
        <button class="small" @click="composeNow(true)" title="丢掉手改内容，按上面各项重新拼接">重新拼接</button>
      </div>
      <textarea rows="5" :value="pr.final" @input="onFinalInput" spellcheck="false"></textarea>
      <div v-if="finalChinese" class="hint err">这里还有中文，生成前会先自动转成英文并让你确认。</div>
      <div v-for="(w, i) in warnFor('final').concat(warnFor('camera'))" :key="'f' + i" class="warnbox">{{ w.text }}</div>
    </div>

    <div class="row">
      <button class="small" @click="S.showGlossary = true">术语表…</button>
      <button class="small" @click="S.showTranslateSettings = true">翻译接口…</button>
      <span class="hint grow">翻译时先套用术语表，再调用翻译接口翻译其余部分。</span>
    </div>
  </div>
</template>

<style scoped>
.pp { display: flex; flex-direction: column; gap: 10px; }
.field textarea { margin-top: 3px; }
.notice { background: #1d3a24; border: 1px solid var(--ok); color: #b8f0cf; padding: 7px 10px; border-radius: 6px; font-weight: 600; }
.warnbox { background: #473a14; border: 1px solid var(--warn); color: #ffe0a0; padding: 5px 8px; border-radius: 5px; font-size: 12px; margin-top: 3px; }
</style>
