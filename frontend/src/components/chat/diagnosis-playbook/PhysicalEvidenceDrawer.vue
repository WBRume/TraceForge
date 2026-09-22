<script setup lang="ts">
import type { EvidenceReceipt } from '@/types/diagnosisPlaybook'
import { onBeforeUnmount, shallowRef } from 'vue'
import api from '@/utils/api'
const props = defineProps<{ receipts: readonly EvidenceReceipt[]; tail: string; workspaceId?: string; taskId?: string; runId?: string }>()
const error = shallowRef('')
const downloading = shallowRef(false)
const abort = new AbortController()
onBeforeUnmount(() => abort.abort())
const download = async (executionId: string, name: string) => {
  if (!props.workspaceId || !props.taskId || !props.runId) return
  downloading.value = true
  error.value = ''
  try {
    const path = name.split('/').map(encodeURIComponent).join('/')
    const { data } = await api.get(`/workspaces/${props.workspaceId}/tasks/${props.taskId}/playbook-runs/${props.runId}/evidence/${executionId}/artifacts/${path}`, { responseType: 'blob', signal: abort.signal })
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = name.split('/').at(-1) || 'evidence'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (failure: any) { if (!abort.signal.aborted) error.value = failure.message }
  finally { downloading.value = false }
}
</script>
<template>
  <details class="physical-evidence">
    <summary>物理证据与实验输出（{{ receipts.length }}）</summary>
    <pre v-if="tail" aria-label="实验实时输出">{{ tail }}</pre>
    <p v-if="error" role="alert">{{ error }}</p>
    <article v-for="receipt in receipts" :key="receipt.execution_id">
      <strong>{{ receipt.execution_id }}</strong>
      <p>退出码 {{ receipt.exit_code }} · {{ receipt.termination }}{{ receipt.timed_out ? ' · 超时' : '' }}</p>
      <code>{{ receipt.receipt_digest }}</code>
      <pre>{{ JSON.stringify(receipt.facts, null, 2) }}</pre>
      <div v-if="workspaceId && taskId && runId"><button v-for="artifact in receipt.artifacts" :key="artifact.name" :disabled="downloading" @click="download(receipt.execution_id, artifact.name)">{{ artifact.name }} · {{ artifact.size }} B</button></div>
    </article>
  </details>
</template>
<style scoped>
.physical-evidence { min-width:0; overflow-wrap:anywhere; margin:12px 0 }.physical-evidence pre { max-height:240px; overflow:auto; white-space:pre-wrap; background:var(--bg-secondary,#f3f4f6); padding:10px }.physical-evidence code { font-size:11px }
</style>
