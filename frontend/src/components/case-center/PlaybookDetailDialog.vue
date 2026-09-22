<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { X, Loader2, Plus, Trash2 } from 'lucide-vue-next'
import api from '@/utils/api'
import type { PlaybookSpec } from '@/types/diagnosisPlaybook'
const props = defineProps<{ item: PlaybookSpec }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const document = ref<any>(null)
const loading = ref(false)
const saving = ref(false)
const editing = ref(false)
const canEdit = ref(false)
const symptoms = ref('')
const error = ref('')
let generation = 0
const addStep = () => document.value.stages.push({ id: 'step_' + crypto.randomUUID().replaceAll('-', ''), objective: '' })
watch(() => props.item.id, async () => {
  const current = ++generation
  loading.value = true; error.value = ''; document.value = null; editing.value = false
  try {
    const { data } = await api.get(`/workspaces/${props.item.workspace_id}/cases/playbooks/${props.item.id}`)
    if (current !== generation) return
    document.value = data.document; canEdit.value = data.can_edit
    symptoms.value = (data.document.match?.symptoms || []).join('\n')
  } catch { if (current === generation) error.value = '规程加载失败' }
  finally { if (current === generation) loading.value = false }
}, { immediate: true })
const save = async () => {
  saving.value = true; error.value = ''
  try {
    const value = JSON.parse(JSON.stringify(document.value))
    value.match = { ...value.match, symptoms: symptoms.value.split('\n').map(v => v.trim()).filter(Boolean) }
    await api.put(`/workspaces/${props.item.workspace_id}/cases/playbooks/${props.item.id}`, { document: value })
    emit('saved')
  } catch (e: any) { error.value = e.response?.data?.detail?.code || '保存失败' }
  finally { saving.value = false }
}
</script>
<template>
  <Teleport to="body">
    <div class="pd-backdrop" @click.self="!saving && emit('close')">
      <section class="pd-dialog" role="dialog" aria-modal="true" aria-label="诊断规程详情">
        <header><h3>诊断规程详情</h3><button aria-label="关闭" :disabled="saving" @click="emit('close')"><X :size="18" /></button></header>
        <div class="pd-body">
          <p v-if="error" role="alert">{{ error }}</p>
          <Loader2 v-if="loading" class="spin" />
          <template v-if="document">
            <label>标题<input v-model="document.metadata.title" :readonly="!editing" /></label>
            <div class="pd-version">版本：{{ document.metadata.version }}</div>
            <label>适用症状<textarea v-model="symptoms" :readonly="!editing" rows="4" /></label>
            <label v-if="document.context">摘要<textarea v-model="document.context.summary" :readonly="!editing" rows="5" /></label>
            <div class="pd-section">诊断步骤</div>
            <div v-for="(step, index) in document.stages" :key="step.id" class="pd-step">
              <span>{{ Number(index) + 1 }}</span><textarea v-model="step.objective" :readonly="!editing" rows="3" />
              <button v-if="editing && document.execution.mode === 'ANALYSIS_GUIDE'" aria-label="删除步骤" @click="document.stages.splice(index, 1)"><Trash2 :size="16" /></button>
              <details v-if="step.verification"><summary>验证配置</summary><pre>{{ JSON.stringify(step.verification, null, 2) }}</pre></details>
            </div>
            <button v-if="editing && document.execution.mode === 'ANALYSIS_GUIDE'" class="btn-secondary" @click="addStep"><Plus :size="14" />添加步骤</button>
            <template v-if="document.metadata.sourceCaseRefs?.length">
              <div class="pd-section">来源案例</div>
              <RouterLink v-for="id in document.metadata.sourceCaseRefs" :key="id" :to="{ name: 'knowledgeCaseDetail', params: { wsId: item.workspace_id, caseId: id } }" @click="emit('close')">{{ document.context?.source_cases?.find((c: any) => c.id === id)?.title || id }}</RouterLink>
            </template>
          </template>
        </div>
        <footer>
          <button class="btn-secondary" :disabled="saving" @click="emit('close')">关闭</button>
          <button v-if="canEdit && document && !editing" class="btn-primary" @click="editing = true">编辑</button>
          <button v-if="editing" class="btn-primary" :disabled="saving || !document?.metadata.title?.trim()" @click="save">{{ saving ? '保存中' : '保存新版本' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
<style scoped>
.pd-backdrop { position: fixed; inset: 0; z-index: 1100; background: #0f172a66; display: flex; align-items: center; justify-content: center; padding: 24px; }
.pd-dialog { background: white; width: 800px; max-width: 100%; max-height: 90vh; border-radius: 16px; display: flex; flex-direction: column; box-shadow: 0 24px 70px #0f172a33; }
header, footer { padding: 18px 24px; display: flex; align-items: center; gap: 12px; }
header { border-bottom: 1px solid #e2e8f0; justify-content: space-between; } header h3 { margin: 0; }
header button, .pd-step > button { display: grid; place-items: center; width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent; color: #64748b; }
header button:hover, .pd-step > button:hover { background: #f1f5f9; }
footer { justify-content: flex-end; border-top: 1px solid #e2e8f0; }
.pd-body { padding: 24px; display: flex; flex-direction: column; gap: 14px; overflow: auto; }
label { display: flex; flex-direction: column; gap: 8px; font-weight: 600; }
input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px; color: #334155; font: inherit; font-weight: 400; resize: vertical; }
input[readonly], textarea[readonly] { background: #f8fafc; border-color: transparent; }
.pd-step { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; } .pd-step textarea { flex: 1; }
.pd-version { color: #64748b; font-size: 12px; } .pd-section { font-weight: 600; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; } button { cursor: pointer; } [role=alert] { color: #dc2626; }
</style>
