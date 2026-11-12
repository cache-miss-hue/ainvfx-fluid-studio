<script setup>
import { ref, computed } from 'vue'
import { S, newProject, flushAll, saveAsCopy, inputDialog, toast, errMsg, startGenerate, genActive, loadSelfcheck, cancelGenerate, restartEngine, freeVram, confirmDialog } from '../store'

const showCheck = ref(false)
const showLan = ref(false)
function copy(t) { try { navigator.clipboard.writeText(t); toast('已复制', 'ok') } catch (_) { /* 局域网 http 页面可能不允许复制 */ } }

const engineText = computed(() => ({
  starting: '引擎启动中…', ready: '引擎就绪', error: '引擎出错', stopped: '引擎未启动', unknown: '连接中…',
}[S.status.engine] || S.status.engine))
const engineCls = computed(() => ({ ready: 'ok', error: 'err', starting: 'warn' }[S.status.engine] || 'dim'))

const issues = computed(() => (S.selfcheck ? S.selfcheck.items.filter((i) => i.level === 'error' || i.level === 'warn') : []))
const hasErr = computed(() => issues.value.some((i) => i.level === 'error'))

async function onNew() {
  const name = await inputDialog('新建项目', '未命名项目', '项目名称')
  if (name === null) return
  try { await flushAll(); await newProject(name) } catch (e) { toast(errMsg(e), 'error') }
}
async function onOpen() { await flushAll(); S.showProjects = true }
async function onSave() {
  const ok = await flushAll()
  toast(ok ? '已保存' : '保存没有完全成功，请看提示', ok ? 'ok' : 'error')
}
async function onCopy() {
  const name = await inputDialog('另存副本', S.project.name + ' 副本', '副本名称（包含参考画面、笔触和设置）')
  if (name === null) return
  try { await saveAsCopy(name) } catch (e) { toast(errMsg(e), 'error') }
}
const canFree = computed(() => S.status.engine === 'ready' && !S.status.busy && !S.status.first_load_pending)
async function onFree() {
  if (await confirmDialog('卸载已加载的模型、释放显存（方便你用显卡做别的事）。下次生成会重新加载模型，多等 1–2 分钟。', '释放显存')) freeVram()
}
const saveText = computed(() => (S.unsavedStrokes || S.projectDirty ? '有改动尚未保存（自动保存中）' : '已保存'))
</script>

<template>
  <div class="topwrap">
  <header class="top">
    <div class="brand">AInVFX<span>Fluid Studio</span></div>
    <input v-if="S.project" class="pname" type="text" v-model="S.project.name" title="点击修改项目名" maxlength="60" />
    <button @click="onNew">新建</button>
    <button @click="onOpen">打开</button>
    <button @click="onSave" title="Ctrl+S">保存</button>
    <button @click="onCopy" :disabled="!S.project">另存副本</button>
    <span class="dim save" :class="{ warn: S.unsavedStrokes || S.projectDirty }">{{ saveText }}</span>
    <div class="grow"></div>
    <div class="check" v-if="S.lan && S.lan.enabled">
      <button @click="showLan = !showLan" title="平板等设备的访问地址和口令">平板访问</button>
      <div v-if="showLan" class="pop" @mouseleave="showLan = false">
        <div class="row"><b class="grow">平板访问（局域网）</b><button class="small" @click="showLan = false">关闭</button></div>
        <p class="dim">在平板浏览器里打开下面的地址（已带口令），浏览器会记住一年。第一个打不开就试下一个。</p>
        <div v-for="u in S.lan.urls" :key="u" class="row lanu"><code class="grow">{{ u }}</code><button class="small" @click="copy(u)">复制</button></div>
        <div v-if="!S.lan.urls.length" class="warn">没找到局域网地址：请确认电脑已连上 Wi-Fi 或网线。</div>
        <p>手动输入用的口令：<b class="tok">{{ S.lan.token }}</b></p>
        <p class="dim">想换口令：删掉软件目录里的 runtime\lan_token.txt 再重新启动（已记住旧口令的设备需要重新输入）。</p>
      </div>
    </div>
    <button @click="S.showTranslateSettings = true" title="设置中文转英文用的外接大模型接口（保存后立即生效）">翻译设置</button>
    <div class="check" v-if="S.selfcheck">
      <button :class="hasErr ? 'bad' : issues.length ? 'warnb' : ''" @click="showCheck = !showCheck">
        {{ hasErr ? '自检：有问题' : issues.length ? '自检：有提醒' : '自检：正常' }}
      </button>
      <div v-if="showCheck" class="pop" @mouseleave="showCheck = false">
        <div class="row"><b class="grow">环境自检</b><button class="small" @click="loadSelfcheck">重新检查</button></div>
        <div v-for="i in S.selfcheck.items" :key="i.name" class="it" :class="i.level">
          <span class="dot"></span>
          <div class="grow"><b>{{ i.name }}</b> <span class="dim">{{ i.detail }}</span>
            <div v-if="i.advice" class="adv">{{ i.advice }}</div></div>
        </div>
      </div>
    </div>
    <span class="eng" :class="engineCls" :title="S.status.engine_error">● {{ engineText }}</span>
    <button v-if="S.status.engine === 'error' || S.status.engine === 'stopped'" class="small" @click="restartEngine"
      :title="S.status.engine_error || '重新启动生成引擎'">重启引擎</button>
    <button v-else-if="canFree" class="small" @click="onFree" title="卸载模型、释放显存，不用关软件">释放显存</button>
    <span v-if="!S.wsOk" class="warn" title="实时连接断开，正在自动重连并改用轮询">连接重试中</span>
    <button v-if="S.project && S.view === 'canvas' && S.results.length" @click="S.currentResult = S.currentResult || S.results[0]; S.view = 'result'">查看结果（{{ S.results.length }}）</button>
    <button v-else-if="S.project && S.view === 'result'" @click="S.view = 'canvas'">返回画布</button>
    <button v-if="genActive" class="gen cancel danger" @click="cancelGenerate">■ 取消生成</button>
    <button v-else class="primary gen" :disabled="!S.project || S.genBusy" @click="startGenerate">
      {{ S.genBusy ? '准备中…' : '▶ 生成' }}
    </button>
  </header>
  <div v-if="S.selfcheck && issues.length" class="banner" :class="hasErr ? 'bad' : 'warnb'" @click="showCheck = true">
    <b>{{ hasErr ? '自检发现问题：' : '自检提醒：' }}</b>
    <span v-for="(i, k) in issues.slice(0, 3)" :key="k">{{ i.name }}（{{ i.detail }}）{{ k < Math.min(issues.length, 3) - 1 ? '；' : '' }}</span>
    <span v-if="issues.length > 3"> 等 {{ issues.length }} 项</span>
    <u>点击查看详情</u>
  </div>
  </div>
</template>

<style scoped>
.topwrap { position: relative; z-index: 20; }
.top { display: flex; align-items: center; gap: 8px; padding: 0 12px; background: var(--bg2); border-bottom: 1px solid var(--line); height: 52px; position: relative; z-index: 20; }
.brand { font-weight: 700; font-size: 15px; color: var(--accent); margin-right: 6px; white-space: nowrap; }
.brand span { color: var(--text); font-weight: 400; margin-left: 5px; font-size: 13px; }
.pname { width: 200px; font-weight: 600; }
.top button, .top .check { white-space: nowrap; flex: none; }
.top .pop { white-space: normal; }
@media (max-width: 1440px) {      /* 平板横屏、小屏：去掉次要文字，按钮不折行 */
  .brand span, .save { display: none; }
  .pname { width: 120px; }
  .top { gap: 6px; }
  .gen { padding: 7px 16px; }
}
.save { font-size: 12px; white-space: nowrap; }
.eng { font-size: 12px; white-space: nowrap; }
.gen { font-size: 16px; padding: 7px 26px; border-radius: 6px; }
.check { position: relative; }
.check button.bad { border-color: var(--err); color: var(--err); }
.check button.warnb { border-color: var(--warn); color: var(--warn); }
.pop { position: absolute; right: 0; top: 36px; width: 460px; max-height: 70vh; overflow: auto; background: var(--bg2); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; box-shadow: 0 10px 40px rgba(0,0,0,.6); }
.it { display: flex; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--line); }
.it .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ok); margin-top: 6px; flex: none; }
.it.warn .dot { background: var(--warn); }
.it.error .dot { background: var(--err); }
.it.info .dot { background: var(--dim); }
.adv { color: var(--warn); font-size: 12px; }
.lanu code { user-select: text; font-size: 13px; background: var(--bg); padding: 3px 6px; border-radius: 4px; word-break: break-all; }
.tok { font-size: 18px; letter-spacing: 2px; color: var(--accent2); user-select: text; }
.it.error .adv { color: var(--err); }
.banner { position: relative; z-index: 15; padding: 4px 14px; font-size: 12px; cursor: pointer; opacity: .96; }
.banner.bad { background: #4a1c1c; color: #ffb3b3; border-bottom: 1px solid var(--err); }
.banner.warnb { background: #473a14; color: #ffe0a0; border-bottom: 1px solid var(--warn); }
.banner u { margin-left: 10px; }
</style>
