<script setup>
import { onMounted, reactive, ref, computed } from 'vue'
import { S, toast, errMsg } from '../store'
import { api } from '../api'

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const showKey = ref(false)
const maskedKey = ref('')
const envFile = ref('')
const form = reactive({
  base_url: '', api_key: '', model: '', wire: 'auto', thinking: 'off',
  timeout: 60, temperature: 0.2, max_tokens: 1000, proxy: '',
})
const testText = ref('浓烟从坦克上冲天而起，橙色火球爆开')
const testResult = ref(null)
const testError = ref('')
const modelsLoading = ref(false)
const models = ref([])
const modelsError = ref('')
const showModelPicker = ref(false)
const modelQuery = ref('')

const configured = computed(() => !!(form.base_url.trim() && form.model.trim()))
const filteredModels = computed(() => {
  const q = modelQuery.value.trim().toLowerCase()
  return q ? models.value.filter((m) => m.toLowerCase().includes(q)) : models.value
})

onMounted(async () => {
  try {
    const c = await api.getTranslateConfig()
    form.base_url = c.base_url || ''
    form.api_key = c.key || ''
    form.model = c.model || ''
    form.wire = c.wire || 'auto'
    form.thinking = c.thinking || 'off'
    form.timeout = c.timeout
    form.temperature = c.temperature
    form.max_tokens = c.max_tokens
    form.proxy = c.proxy || ''
    maskedKey.value = c.key || ''
    envFile.value = c.env_file || ''
  } catch (e) { toast('读取翻译设置失败：' + errMsg(e), 'error') }
  loading.value = false
})

// 密钥原样传回打码形式 = 不修改；后端负责沿用旧值 / 换新 / 清空
function payload() {
  return {
    base_url: form.base_url.trim(),
    api_key: form.api_key.trim(),
    model: form.model.trim(),
    wire: form.wire,
    thinking: form.thinking,
    timeout: form.timeout,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    proxy: form.proxy.trim(),
  }
}

async function save() {
  saving.value = true
  try {
    await api.putTranslateConfig(payload())
    toast('翻译接口设置已保存，立即生效', 'ok')
    S.showTranslateSettings = false
  } catch (e) { toast('保存失败：' + errMsg(e), 'error') }
  finally { saving.value = false }
}

async function runTest() {
  testing.value = true
  testResult.value = null
  testError.value = ''
  try {
    testResult.value = await api.testTranslate(testText.value.trim() || undefined, payload())
  } catch (e) { testError.value = errMsg(e) }
  finally { testing.value = false }
}

async function fetchModels() {
  modelsLoading.value = true
  modelsError.value = ''
  try {
    const r = await api.listTranslateModels(payload())
    if (r.ok) {
      models.value = r.models || []
      modelQuery.value = ''
      showModelPicker.value = true
    } else {
      modelsError.value = r.error || '拉取模型失败'
      showModelPicker.value = false
    }
  } catch (e) {
    modelsError.value = errMsg(e)
    showModelPicker.value = false
  } finally { modelsLoading.value = false }
}

function pickModel(m) {
  form.model = m
  showModelPicker.value = false
}
</script>

<template>
  <div class="mask" @mousedown.self="S.showTranslateSettings = false">
    <div class="box">
      <div class="row">
        <h3 class="grow">翻译接口设置</h3>
        <span class="badge" :class="configured ? 'ok' : 'dim'">{{ configured ? '已配置' : '未配置' }}</span>
        <button class="small" @click="S.showTranslateSettings = false">关闭</button>
      </div>
      <p class="hint">「转英文」用的外接大模型接口，不占本机显存，只有点翻译时才会联网。保存后立即生效，不用重启软件。</p>

      <div v-if="loading" class="dim">读取中…</div>
      <div v-else class="body">
        <div class="field">
          <span class="lbl">接口地址（Base URL）</span>
          <input type="text" v-model="form.base_url" placeholder="https://api.deepseek.com（带不带 /v1 都行）" spellcheck="false" />
        </div>
        <div class="field">
          <span class="lbl">API Key（密钥）</span>
          <div class="row">
            <input class="grow" :type="showKey ? 'text' : 'password'" v-model="form.api_key"
                   placeholder="sk-…（本机 Ollama / LM Studio 可不填）" spellcheck="false" autocomplete="off" />
            <button class="small" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button>
          </div>
          <div class="hint">{{ maskedKey ? `当前密钥 ${maskedKey}（打码）。保持原样 = 不修改；全选删掉填新的 = 更换；清空后保存 = 删除密钥。` : '还没有密钥。云端接口一般需要；本机 Ollama / LM Studio 可以不填。' }}</div>
        </div>
        <div class="field">
          <span class="lbl">模型名</span>
          <div class="row">
            <input class="grow" type="text" v-model="form.model" placeholder="deepseek-chat（可手动填，或点右边拉取后选择）" spellcheck="false" />
            <button :disabled="modelsLoading || !form.base_url.trim()" @click="fetchModels"
                    title="从接口地址拉取可选模型列表">{{ modelsLoading ? '拉取中…' : '拉取模型' }}</button>
          </div>
          <div v-if="modelsError" class="warnbox errbox">{{ modelsError }}</div>
          <div v-if="showModelPicker" class="picker">
            <div class="row">
              <input class="grow" type="text" v-model="modelQuery" placeholder="搜索模型…" spellcheck="false" />
              <span class="dim count">{{ filteredModels.length }} / {{ models.length }}</span>
              <button class="small" @click="showModelPicker = false">收起</button>
            </div>
            <div class="plist">
              <button v-for="m in filteredModels" :key="m" class="pitem" :class="{ on: m === form.model }"
                      @click="pickModel(m)" :title="m">{{ m }}</button>
              <div v-if="!filteredModels.length" class="dim none">没有匹配的模型</div>
            </div>
          </div>
        </div>
        <div class="grid2">
          <div class="field">
            <span class="lbl">接口格式</span>
            <select v-model="form.wire">
              <option value="auto">自动识别（推荐）</option>
              <option value="chat">OpenAI Chat Completions（DeepSeek、通义、Kimi、大多数中转站）</option>
              <option value="responses">OpenAI Responses</option>
              <option value="anthropic">Anthropic Messages（Claude）</option>
            </select>
          </div>
          <div class="field">
            <span class="lbl">深度推理</span>
            <select v-model="form.thinking">
              <option value="off">关闭（更快更省，推荐）</option>
              <option value="auto">按模型默认</option>
            </select>
          </div>
        </div>

        <div class="sec">高级选项（一般不用改）</div>
        <div class="grid2">
          <div class="field">
            <span class="lbl">超时（秒，5–600）</span>
            <input type="number" v-model.number="form.timeout" min="5" max="600" step="1" />
          </div>
          <div class="field">
            <span class="lbl">随机性（0–2，越低越稳定）</span>
            <input type="number" v-model.number="form.temperature" min="0" max="2" step="0.1" />
          </div>
          <div class="field">
            <span class="lbl">最大输出长度（50–32000）</span>
            <input type="number" v-model.number="form.max_tokens" min="50" max="32000" step="50" />
          </div>
          <div class="field">
            <span class="lbl">代理</span>
            <input type="text" v-model="form.proxy" placeholder="留空跟随系统；none 强制直连；或 http://127.0.0.1:7890" spellcheck="false" />
          </div>
        </div>

        <div class="sec">测试翻译（用当前表单的值，不用先保存）</div>
        <div class="row">
          <input type="text" class="grow" v-model="testText" placeholder="写一句中文试试" @keydown.enter="runTest" />
          <button :disabled="testing" @click="runTest">{{ testing ? '测试中…' : '发送测试' }}</button>
        </div>
        <div v-if="testError" class="warnbox errbox">{{ testError }}</div>
        <template v-if="testResult">
          <div v-if="testResult.warning" class="warnbox">{{ testResult.warning }}</div>
          <div class="result" :class="{ ok: testResult.method === 'api' }">
            <div>{{ testResult.english || '（没有输出）' }}</div>
            <div v-if="testResult.method === 'api'" class="dim meta">
              协议 {{ testResult.wire }} · 模型 {{ testResult.model }} · 耗时 {{ testResult.elapsed }} 秒
            </div>
            <div v-else-if="testResult.method === 'unchanged'" class="dim meta">这句本来就是英文，没有调用接口。</div>
          </div>
        </template>
      </div>

      <div class="row end">
        <span class="dim env grow" :title="envFile">配置保存在 {{ envFile }}，也可以直接用记事本编辑</span>
        <button @click="S.showTranslateSettings = false">取消</button>
        <button class="primary" :disabled="saving || loading" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; z-index: 90; }
.box { background: var(--bg2); border: 1px solid var(--line); border-radius: 8px; padding: 14px 18px; width: 680px; max-width: 94vw; max-height: 88vh; display: flex; flex-direction: column; gap: 8px; }
h3 { margin: 0; font-size: 15px; }
.badge.ok { background: #1d3a24; color: var(--ok); }
.body { overflow: auto; display: flex; flex-direction: column; gap: 8px; min-height: 0; padding-right: 4px; }
.field input[type=text], .field input[type=password], .field input[type=number], .field select { width: 100%; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; }
.sec { font-weight: 600; font-size: 12px; color: var(--dim); border-top: 1px solid var(--line); padding-top: 8px; margin-top: 2px; }
.warnbox { background: #473a14; border: 1px solid var(--warn); color: #ffe0a0; padding: 5px 8px; border-radius: 5px; font-size: 12px; }
.errbox { background: #4a1c1c; border-color: var(--err); color: #ffb3b3; }
.result { background: var(--bg); border: 1px solid var(--line); border-radius: 5px; padding: 6px 9px; user-select: text; }
.result.ok { border-color: var(--ok); }
.result .meta { font-size: 12px; margin-top: 3px; }
.picker { border: 1px solid var(--line); border-radius: 6px; background: var(--bg); padding: 6px; display: flex; flex-direction: column; gap: 5px; margin-top: 4px; }
.count { font-size: 11px; white-space: nowrap; }
.plist { max-height: 180px; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
.pitem { width: 100%; text-align: left; background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 3px 7px; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pitem:hover:not(:disabled) { background: var(--bg3); border-color: var(--line); }
.pitem.on { background: #3a2a1a; border-color: var(--accent); color: var(--accent2); }
.none { padding: 6px; font-size: 12px; }
.end { justify-content: flex-end; border-top: 1px solid var(--line); padding-top: 10px; }
.env { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>