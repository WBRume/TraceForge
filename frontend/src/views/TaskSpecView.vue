<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, AlertCircle } from '@/components/icons'
import DocReviewWorkbench from '@/components/doc-review/DocReviewWorkbench.vue'
import PlanDocsPanel from '@/components/chat/PlanDocsPanel.vue'
import { useTaskSpecBootstrapFeed } from '@/composables/useTaskSpecBootstrapFeed'
import { useWorkspaceContext } from '@/composables/chat/tasklist/useWorkspaceContext'
import { isCanvasRoute } from '@/router/workspaceAssetPresentation'
import api from '@/utils/api'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const wsId = computed(() => String(route.params.wsId || ''))
const taskId = computed(() => String(route.params.taskId || ''))
const embedded = computed(() => isCanvasRoute(route))
const planContext = useWorkspaceContext({ getWorkspaceId: () => wsId.value })
const revisionJobId = computed(() => typeof route.query.revisionJob === 'string' ? route.query.revisionJob : '')
const assetId = computed(() => typeof route.query.asset === 'string' ? route.query.asset : undefined)
const versionId = computed(() => typeof route.query.version === 'string' ? route.query.version : undefined)
const blockId = computed(() => typeof route.query.block === 'string' ? route.query.block : undefined)
const documentKey = computed(() => [assetId.value, versionId.value, blockId.value].join(':'))
const planFile = computed<{ section: 'plans' | 'specs'; path: string } | undefined>(() => {
  const { plan, path } = route.query
  if ((plan === 'plans' || plan === 'specs') && typeof path === 'string' && path) return { section: plan, path }
  return undefined
})
watch([wsId, () => Boolean(planFile.value), embedded], ([workspaceId, plan, canvas]) => {
  if (workspaceId && plan && canvas) void planContext.loadWorkspace().catch(() => {})
}, { immediate: true })

const clearRevisionJob = (jobId: string) => {
  if (revisionJobId.value !== jobId) return
  const query = { ...route.query }
  delete query.revisionJob
  void router.replace({ query })
}

const specBootstrapFeed = useTaskSpecBootstrapFeed({ wsId, taskId })

const taskStatus = ref('')

const docReadonly = computed(() => {
  if (!taskId.value) return true
  if (!taskStatus.value) return false
  return taskStatus.value !== 'INITIALIZED'
})

const loadTaskStatus = async () => {
  if (!wsId.value || !taskId.value) {
    taskStatus.value = ''
    return
  }
  const workspaceId = wsId.value
  const currentTaskId = taskId.value
  const current = () => wsId.value === workspaceId && taskId.value === currentTaskId
  taskStatus.value = ''
  try {
    const res = await api.get(`/workspaces/${workspaceId}/tasks/${currentTaskId}`)
    if (current()) taskStatus.value = String(res.data?.status || '')
  } catch {
    if (current()) taskStatus.value = ''
  }
}

watch(
  () => [wsId.value, taskId.value] as const,
  () => {
    void loadTaskStatus()
  },
  { immediate: true },
)

const backToChat = () => {
  if (!wsId.value || !taskId.value) return
  router.push(`/workspaces/${wsId.value}/chat/${taskId.value}`)
}
</script>

<template>
  <div class="task-spec-view" :class="{ embedded }">
    <div v-if="docReadonly && !planFile" class="readonly-banner fade-in">
      <AlertCircle class="w-4 h-4" />
      <span>
        {{ t('doc_review.task_readonly_banner_prefix') }}<strong>{{ t('doc_review.readonly_mode') }}</strong>
      </span>
    </div>

    <section v-if="planFile" class="workbench-shell plan-workbench fade-in-visible">
      <button class="btn-secondary btn-back" @click="backToChat">
        <ArrowLeft class="w-4 h-4" />{{ t('doc_review.back_to_chat') }}
      </button>
      <PlanDocsPanel :key="`${taskId}:${planFile.section}:${planFile.path}`" :ws-id="wsId" :task-id="taskId"
        :initial-file="planFile" :readonly="!embedded || !planContext.canEditPlanDocs.value" />
    </section>
    <section v-else class="workbench-shell fade-in-visible">
      <DocReviewWorkbench
        :key="documentKey"
        :ws-id="wsId"
        :task-id="taskId"
        :initial-asset-id="assetId"
        :initial-version-id="versionId"
        :focus-block-id="blockId"
        :readonly="docReadonly"
        :bootstrap-status="specBootstrapFeed.bootstrap.value"
        :revision-job-id="revisionJobId"
        compact
        @revision-job-opened="clearRevisionJob"
      >
        <template #header-prefix>
          <button class="btn-secondary btn-back" @click="backToChat">
            <ArrowLeft class="w-4 h-4" />
            {{ t('doc_review.back_to_chat') }}
          </button>
        </template>
      </DocReviewWorkbench>
    </section>
  </div>
</template>

<style scoped>
.task-spec-view {
  height: var(--app-viewport-height, 100vh);
  min-height: 0;
  padding: 1rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  background-color: var(--color-bg-base);
  background-image: 
    radial-gradient(circle at 10% 20%, var(--color-primary-50) 0%, transparent 40%),
    radial-gradient(circle at 90% 80%, #f0f9ff 0%, transparent 40%);
  font-family: var(--font-body);
}

.readonly-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  background: rgba(3, 105, 161, 0.08);
  border: 1px solid rgba(14, 165, 233, 0.2);
  color: #0369a1;
  padding: 0.6rem 1rem;
  border-radius: var(--radius-lg);
  font-size: 0.875rem;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.05);
}

.readonly-banner strong {
  font-weight: 600;
}

.btn-back {
  border-radius: 999px;
  padding: 0.5rem 1.25rem;
  box-shadow: var(--shadow-sm);
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.workbench-shell {
  min-height: 0;
  flex: 1;
}
.plan-workbench { display: flex; flex-direction: column; gap: 10px; }
.plan-workbench .btn-back { align-self: flex-start; }
.task-spec-view.embedded { height: 100%; padding: 12px; }

/* Animations matching Portal */
.fade-in {
  animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

.fade-in-visible {
  animation: slideUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.w-4 { width: 1rem; height: 1rem; }
.h-4 { width: 1rem; height: 1rem; }
</style>
