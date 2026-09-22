<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import api from '@/utils/api'
const props = defineProps<{ workspaceId: string; caseId: string; canManage: boolean }>()
const revisions = shallowRef<Record<string, any>[]>([])
const error = shallowRef('')
const busy = shallowRef(false)
const editing = shallowRef<string | null>(null)
const draft = shallowRef('')
let generation = 0
watch(() => [props.workspaceId, props.caseId], async (_value, _old, cleanup) => {
  const captured = ++generation
  const abort = new AbortController()
  cleanup(() => abort.abort())
  revisions.value = []
  error.value = ''
  busy.value = false
  editing.value = null
  try {
    const { data } = await api.get(`/workspaces/${props.workspaceId}/cases/${props.caseId}/technical-revisions`, { signal: abort.signal })
    if (captured === generation) revisions.value = data.items
  } catch (e: any) { if (!abort.signal.aborted) error.value = e.response?.data?.detail?.code || e.message }
}, { immediate: true })
const editDraft = (revision: Record<string, any>) => { editing.value = revision.extraction_id; draft.value = JSON.stringify(revision.spec_candidate, null, 2) }
const saveDraft = async () => {
  if (!editing.value) return
  const captured = generation
  const id = editing.value
  busy.value = true
  try {
    const { data } = await api.post(`/workspaces/${props.workspaceId}/cases/${props.caseId}/playbook-extractions/${id}/spec`, { document: draft.value })
    if (captured === generation) {
      revisions.value = revisions.value.map(revision => revision.extraction_id === id ? { ...revision, linked_spec_id: data.id } : revision)
      editing.value = null
    }
  } catch (e: any) { if (captured === generation) error.value = e.response?.data?.detail?.code || e.message }
  finally { if (captured === generation) busy.value = false }
}
</script>
<template>
  <section class="case-playbooks">
    <header><strong>诊断规程与验证记录</strong></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!revisions.length">尚无规程来源或物理验证记录。</p>
    <article v-for="revision in revisions" :key="revision.run_id || revision.linked_spec_id || revision.source_digest">
      <template v-if="revision.run_id">
        <p>规程 {{ revision.spec_version }} · 执行 {{ revision.run_id }}</p>
        <p>验证环境：{{ revision.environment?.enforcement || '参见原始回执' }}</p>
        <code>{{ revision.projection_digest }}</code>
        <ul><li v-for="gate in revision.gate_decisions" :key="gate.execution_id">{{ gate.step_id }} · {{ gate.verdict }} · {{ gate.execution_id }}</li></ul>
      </template>
      <template v-else-if="revision.kind === 'CASE_PROMOTION' || revision.kind === 'PLAYBOOK_EDIT'">
        <p>{{ revision.kind === 'PLAYBOOK_EDIT' ? '规程已修订' : '已晋升' }}：{{ revision.spec_candidate?.metadata?.title }} · {{ revision.spec_candidate?.metadata?.version }}</p>
        <p>{{ revision.spec_candidate?.context?.summary }}</p>
        <details><summary>查看定位方法</summary><ol><li v-for="step in revision.spec_candidate?.stages" :key="step.id">{{ step.objective }}</li></ol></details>
      </template>
      <template v-else><p>已提取规程候选，尚未完成环境验证。</p><p>待补充：{{ revision.unresolved_inputs?.join('、') }}</p>
        <p v-if="revision.linked_spec_id">已保存规程版本，可在新建任务时选择复用。</p>
        <button v-else-if="canManage && revision.spec_candidate" @click="editDraft(revision)">编辑并校验候选</button>
        <div v-if="editing === revision.extraction_id"><textarea v-model="draft" rows="16" aria-label="规程候选 YAML 或 JSON" /><button :disabled="busy" @click="saveDraft">校验并保存规程版本</button></div>
      </template>
    </article>
  </section>
</template>
<style scoped>
.case-playbooks textarea { display:block; width:100%; padding:8px; margin:8px 0; font-family:monospace }
.case-playbooks { padding:16px; border:1px solid var(--border-color,#ddd); border-radius:8px; margin:16px 0; min-width:0; overflow-wrap:anywhere }.case-playbooks header { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap }.case-playbooks button { padding:4px 10px; border:1px solid var(--border-color,#ddd); border-radius:4px }.case-playbooks code { font-size:11px }
</style>
