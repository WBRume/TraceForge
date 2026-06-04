<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, AlertCircle } from 'lucide-vue-next'
import DocReviewWorkbench from '@/components/doc-review/DocReviewWorkbench.vue'
import api from '@/utils/api'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const wsId = computed(() => String(route.params.wsId || ''))
const taskId = computed(() => String(route.params.taskId || ''))

const taskStatus = ref('')

const docReadonly = computed(() => {
  if (!taskId.value) return true
  if (!taskStatus.value) return false
  return taskStatus.value !== 'PENDING'
})

const loadTaskStatus = async () => {
  if (!wsId.value || !taskId.value) {
    taskStatus.value = ''
    return
  }
  try {
    const res = await api.get(`/workspaces/${wsId.value}/tasks/${taskId.value}`)
    taskStatus.value = String(res.data?.status || '')
  } catch {
    taskStatus.value = ''
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
  router.push(`/ws/${wsId.value}/chat/${taskId.value}`)
}
</script>

<template>
  <div class="task-spec-view">
    <div v-if="docReadonly" class="readonly-banner fade-in">
      <AlertCircle class="w-4 h-4" />
      <span>
        {{ t('doc_review.task_readonly_banner_prefix') }}<strong>{{ t('doc_review.readonly_mode') }}</strong>
      </span>
    </div>

    <section class="workbench-shell fade-in-visible">
      <DocReviewWorkbench
        :ws-id="wsId"
        :task-id="taskId"
        :readonly="docReadonly"
        compact
      >
        <template #header-prefix>
          <div class="head-brand">
            <h2 class="title-gradient">{{ t('doc_review.task_spec_title') }}</h2>
            <span class="badge-tag">{{ t('doc_review.task_session_badge') }}</span>
          </div>
        </template>
        <template #header-actions>
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
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');

.task-spec-view {
  height: 100vh;
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

.head-brand {
  display: flex;
  align-items: center;
  gap: 1rem;
  min-width: 0;
  flex-wrap: wrap;
}

.title-gradient {
  margin: 0;
  font-family: var(--font-heading), 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.badge-tag {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  border: 1px solid var(--color-primary-100);
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
