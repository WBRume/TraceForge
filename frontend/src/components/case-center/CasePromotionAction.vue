<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, watch } from 'vue'
import router from '@/router'
import api from '@/utils/api'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { useProvisioningStore } from '@/stores/provisioning'
import { ElMessage } from 'element-plus'

const props = defineProps<{ workspaceId: string; caseIds: string[]; requestedJobId?: string }>()
const emit = defineEmits<{ completed: [] }>()
const floating = useProvisioningStore()
const confirm = shallowRef(false)
const busy = shallowRef(false)
const error = shallowRef('')
const pendingCases = shallowRef<string[]>([])
const pendingWorkspace = shallowRef('')
let key = ''
const activeCount = computed(() => floating.jobList.filter(job =>
  job.workspaceId === props.workspaceId && job.kind === 'playbook_promotion' && !job.terminal,
).length)

const showConfirm = () => {
  pendingCases.value = [...props.caseIds]
  pendingWorkspace.value = props.workspaceId
  key = crypto.randomUUID()
  error.value = ''
  confirm.value = true
}
const start = async () => {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { data } = await api.post(`/workspaces/${pendingWorkspace.value}/cases/playbook-promotions`, {
      case_ids: pendingCases.value, idempotency_key: key,
    })
    floating.ingestPromotionJob(data)
    confirm.value = false
    ElMessage.success('晋升任务已加入后台队列')
  } catch (e: any) {
    error.value = e.response?.data?.detail?.code === 'CASE_NOT_APPROVED'
      ? '只有评审入库的案例才能晋升，请刷新案例列表' : '晋升提交失败，请重试'
  } finally { busy.value = false }
}
const reload = async () => {
  if (props.workspaceId) await floating.refreshPromotionJobs(props.workspaceId)
}
const onUpdate = (event: Event) => {
  const detail = (event as CustomEvent).detail
  if (detail?.workspace_id !== props.workspaceId) return
  void reload()
  if (detail.review_state === 'CONFIRMED') emit('completed')
}
// Compatibility for old notifications: only a generated draft opens the review page.
watch(() => [props.workspaceId, props.requestedJobId], async () => {
  await reload()
  const job = props.requestedJobId ? floating.getTrackedJob(props.requestedJobId) : null
  if (job?.reviewRequired) void router.push({ name: 'workspaceCasePromotionReview', params: {
    wsId: props.workspaceId, jobId: job.jobId,
  } })
}, { immediate: true })
onMounted(() => window.addEventListener('playbook-promotion-updated', onUpdate))
onUnmounted(() => window.removeEventListener('playbook-promotion-updated', onUpdate))
</script>

<template>
  <button class="btn-primary" :disabled="busy || !workspaceId || !caseIds.length || caseIds.length > 20" @click="showConfirm">
    晋升诊断规程{{ caseIds.length ? `（${caseIds.length}）` : '' }}
  </button>
  <span v-if="activeCount" role="status">{{ activeCount }} 个晋升任务执行中</span>
  <span v-if="error" role="alert">{{ error }}</span>
  <ConfirmActionModal :show="confirm" title="案例晋升诊断规程" :message="`将所选 ${pendingCases.length} 个案例交给 AI 提炼诊断规程与症状短语。`"
    cancel-text="取消" confirm-text="开始晋升" tone="primary" :loading="busy" @cancel="confirm = false" @confirm="start" />
</template>
