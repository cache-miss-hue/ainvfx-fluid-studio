<script setup>
import { onMounted, ref } from 'vue'
import { S, openProject, refreshProjectList, errMsg, toast, deleteProject } from '../store'

const loading = ref(true)
onMounted(async () => {
  try { await refreshProjectList() } catch (e) { toast(errMsg(e), 'error') }
  loading.value = false
})
async function open(id) {
  try { await openProject(id); S.showProjects = false } catch (e) { toast('打开失败：' + errMsg(e), 'error') }
}
async function del(p) { await deleteProject(p.id, p.name) }
const fmt = (t) => new Date(t * 1000).toLocaleString('zh-CN', { hour12: false })
</script>

<template>
  <div class="mask" @mousedown.self="S.showProjects = false">
    <div class="box">
      <div class="row"><h3 class="grow">打开项目</h3><button class="small" @click="S.showProjects = false">关闭</button></div>
      <div v-if="loading" class="dim">读取中…</div>
      <div v-else-if="!S.projectList.length" class="dim">还没有项目</div>
      <div class="list">
        <div v-for="p in S.projectList" :key="p.id" class="item" :class="{ cur: p.id === S.pid }" @click="open(p.id)">
          <span class="nm">{{ p.name }}</span>
          <span class="dim">{{ fmt(p.mtime) }}</span>
          <span v-if="p.id === S.pid" class="badge">当前</span>
          <button class="small danger" title="删除项目（移到回收站）" @click.stop="del(p)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; z-index: 90; }
.box { background: var(--bg2); border: 1px solid var(--line); border-radius: 8px; padding: 14px 18px; width: 520px; max-height: 70vh; display: flex; flex-direction: column; }
h3 { margin: 0; font-size: 15px; }
.list { overflow: auto; margin-top: 8px; }
.item { display: flex; gap: 10px; align-items: center; padding: 7px 8px; border-radius: 5px; cursor: pointer; }
.item:hover { background: var(--bg3); }
.item.cur { outline: 1px solid var(--accent); }
.nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
