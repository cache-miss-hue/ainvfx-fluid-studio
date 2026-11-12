<script setup>
import { onMounted, ref, computed } from 'vue'
import { S, toast, errMsg } from '../store'
import { api } from '../api'

const builtin = ref({})
const rows = ref([]) // [{zh,en}]
const loading = ref(true)
const q = ref('')
onMounted(async () => {
  try {
    const g = await api.getGlossary()
    builtin.value = g.builtin || {}
    rows.value = Object.entries(g.user || {}).map(([zh, en]) => ({ zh, en }))
  } catch (e) { toast('读取术语表失败：' + errMsg(e), 'error') }
  loading.value = false
})
const builtinList = computed(() => Object.entries(builtin.value).filter(([k, v]) => !q.value || k.includes(q.value) || v.toLowerCase().includes(q.value.toLowerCase())))
function add() { rows.value.push({ zh: '', en: '' }) }
function del(i) { rows.value.splice(i, 1) }
async function save() {
  const user = {}
  for (const r of rows.value) if (r.zh.trim() && r.en.trim()) user[r.zh.trim()] = r.en.trim()
  try { await api.putGlossary(user); toast('术语表已保存', 'ok'); S.showGlossary = false } catch (e) { toast('保存失败：' + errMsg(e), 'error') }
}
</script>

<template>
  <div class="mask" @mousedown.self="S.showGlossary = false">
    <div class="box">
      <div class="row"><h3 class="grow">术语表</h3><button class="small" @click="S.showGlossary = false">关闭</button></div>
      <p class="hint">翻译时先按术语表把中文词换成固定英文，再翻译剩下的部分。你加的词优先于内置词。</p>
      <div v-if="loading" class="dim">读取中…</div>
      <div class="cols">
        <div class="col">
          <div class="row"><b class="grow">我的术语</b><button class="small" @click="add">+ 添加</button></div>
          <div class="scroll">
            <div v-for="(r, i) in rows" :key="i" class="row ent">
              <input type="text" v-model="r.zh" placeholder="中文" style="width:38%" />
              <input type="text" v-model="r.en" placeholder="English" class="grow" />
              <button class="small danger" @click="del(i)">删</button>
            </div>
            <div v-if="!rows.length" class="dim">还没有自己的术语</div>
          </div>
        </div>
        <div class="col">
          <div class="row"><b class="grow">内置（只读）</b><input type="text" v-model="q" placeholder="搜索" style="width:110px" /></div>
          <div class="scroll">
            <div v-for="[k, v] in builtinList" :key="k" class="row ro"><span class="zh">{{ k }}</span><span class="dim grow">{{ v }}</span></div>
          </div>
        </div>
      </div>
      <div class="row end"><button @click="S.showGlossary = false">取消</button><button class="primary" @click="save">保存</button></div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; z-index: 90; }
.box { background: var(--bg2); border: 1px solid var(--line); border-radius: 8px; padding: 14px 18px; width: 860px; max-width: 94vw; height: 70vh; display: flex; flex-direction: column; gap: 6px; }
h3 { margin: 0; font-size: 15px; }
.cols { display: flex; gap: 16px; flex: 1; min-height: 0; }
.col { flex: 1; display: flex; flex-direction: column; min-width: 0; gap: 6px; }
.scroll { overflow: auto; flex: 1; display: flex; flex-direction: column; gap: 4px; }
.ent { gap: 4px; }
.ro { font-size: 12px; padding: 1px 0; border-bottom: 1px solid var(--line); }
.zh { width: 40%; }
.end { justify-content: flex-end; }
</style>
