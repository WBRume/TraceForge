<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import CodeComparison from './CodeComparison.vue'
import { Check, AlertCircle } from '@/components/icons'
import type { UpdateFileDetail } from '@/services/repositoryUpdates'

const props = defineProps<{ detail: UpdateFileDetail; busy: boolean; editable: boolean; path?: string; savedDraft?: { text: string; version: number } }>()
const emit = defineEmits<{ resolve: [choice: string, text?: string, version?: number]; draft: [value: { text: string; version: number } | null] }>()
const draft = ref(''), dirty = ref(false), staleDraft = ref(false)
const binary = computed(() => Object.values(props.detail.versions).some(v => v.binary || ['120000', '160000'].includes(v.mode || '')))
const taskVersion = computed(() => props.detail.conflict ? props.detail.versions.task : props.detail.versions.result)
watch(() => props.detail, (detail, previous) => {
  if (!previous && props.savedDraft) {
    draft.value = props.savedDraft.text; dirty.value = true; staleDraft.value = props.savedDraft.version !== detail.version; return
  }
  if (previous?.path === detail.path && dirty.value && (detail.conflict || draft.value !== detail.versions.result.text)) {
    staleDraft.value = true; return
  }
  draft.value = taskVersion.value.text; dirty.value = false; staleDraft.value = false
}, { immediate: true })
function edit(text: string) { draft.value = text; dirty.value = true; emit('draft', { text, version:staleDraft.value && props.savedDraft ? props.savedDraft.version : props.detail.version }) }
function useLatest() { draft.value = taskVersion.value.text; dirty.value = false; staleDraft.value = false; emit('draft', null) }
function keepDraft() { staleDraft.value = false; emit('draft', { text:draft.value, version:props.detail.version }) }
function resolve(choice: string) { emit('resolve', choice, choice === 'edit' ? draft.value : undefined, props.detail.version) }
</script>

<template>
  <section class="update-file">
    <div v-if="staleDraft" class="draft-warning" role="status">
      <AlertCircle :size="14" /><span>预览已有更新，你的编辑已保留。</span>
      <button type="button" @click="useLatest">加载最新结果</button>
      <button type="button" @click="keepDraft">继续使用我的编辑</button>
    </div>
    <CodeComparison v-if="!binary" :path="path || detail.path"
      :left-text="detail.versions.remote.text" :right-text="draft"
      :left-exists="detail.versions.remote.exists" :right-exists="dirty || taskVersion.exists"
      left-label="远端版本 · 最新基线"
      :right-label="`任务版本${dirty ? ' · 未确认' : detail.resolved ? ' · 已确认' : detail.conflict ? '' : ' · 整合后'}`"
      :editable="editable && !busy" @update:right-text="edit">
      <template #tools>
        <span class="file-state" :class="{ warning: detail.conflict }">
          <AlertCircle v-if="detail.conflict" :size="13" /><Check v-else :size="13" />
          {{ detail.conflict ? '待处理冲突' : detail.resolved ? '已确认结果' : '自动整合' }}
        </span>
      </template>
    </CodeComparison>
    <div v-else class="binary-versions">
      <strong>{{ path || detail.path }}</strong>
      <div><span>远端版本 · 最新基线</span><span>任务版本</span></div>
      <p>二进制、大文件或链接不支持文本编辑，请选择完整版本。</p>
    </div>
    <footer v-if="editable" class="resolution-actions">
      <div class="version-choices">
        <button type="button" :disabled="busy" @click="resolve('task')">{{ detail.versions.task.exists ? '使用任务版本' : '按任务版本删除' }}</button>
        <button type="button" :disabled="busy" @click="resolve('remote')">{{ detail.versions.remote.exists ? '使用远端版本' : '按远端版本删除' }}</button>
        <button type="button" class="delete" :disabled="busy" @click="resolve('delete')">删除文件</button>
      </div>
      <button v-if="!binary" class="primary" type="button" :disabled="busy || staleDraft || (!dirty && !detail.conflict)" @click="resolve('edit')"><Check :size="13" />确认此文件结果</button>
    </footer>
  </section>
</template>

<style scoped>
.update-file { display:flex; flex:1; flex-direction:column; min-width:0; min-height:0; overflow:hidden; background:#fff; }
.file-state { display:inline-flex; gap:5px; align-items:center; font-size:11px; color:#059669; }
.file-state.warning { color:#b45309; }
.resolution-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:10px 14px; border-top:1px solid #e2e8f0; }
.version-choices { display:flex; flex-wrap:wrap; gap:6px; margin-right:auto; }
button { display:inline-flex; align-items:center; gap:5px; min-height:30px; padding:5px 9px; border:1px solid #cbd5e1; border-radius:6px; background:#fff; color:#334155; font-size:11px; cursor:pointer; }
button:hover:not(:disabled) { background:#f1f5f9; }
button:disabled { opacity:.45; cursor:default; }
button:focus-visible { outline:2px solid #38bdf8; outline-offset:2px; }
button.primary { background:#0284c7; color:white; border-color:#0284c7; }
button.primary:hover:not(:disabled) { background:#0369a1; }
button.delete { color:#be123c; border-color:transparent; }
.draft-warning { display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:8px 14px; background:#fffbeb; color:#92400e; font-size:12px; }
.binary-versions { flex:1; padding:20px; color:#64748b; font-size:12px; }
.binary-versions div { display:grid; grid-template-columns:1fr 1fr; padding:18px 0; }
</style>
