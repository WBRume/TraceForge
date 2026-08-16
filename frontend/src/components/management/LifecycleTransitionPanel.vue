<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import LifecycleBadge from '@/components/management/LifecycleBadge.vue'
import { transitionProjectLifecycle } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import { LIFECYCLE_FLOW, LIFECYCLE_PREV } from '@/types/management'
import type { Project, ProjectDetail, ProjectLifecycleStatus } from '@/types/management'

const props = defineProps<{
  project: ProjectDetail;
  canManage: boolean;
}>()

const emit = defineEmits<{
  (e: 'changed', project: Project): void;
}>()

const { t } = useI18n()

const flowOrder: ProjectLifecycleStatus[] = [
  'INITIATED',
  'DEVELOPING',
  'DELIVERING',
  'MAINTAINING',
  'RETIRED',
]

const currentIndex = computed(() => flowOrder.indexOf(props.project.lifecycle_status))

const stageLabels = computed(() =>
  flowOrder.map((status) => ({
    status,
    label: t('management.project.lifecycle_' + status.toLowerCase()),
  }))
)

const lifecycleLabel = (status: ProjectLifecycleStatus): string =>
  t('management.project.lifecycle_' + status.toLowerCase())

const nextStatus = computed<ProjectLifecycleStatus | null>(
  () => LIFECYCLE_FLOW[props.project.lifecycle_status] ?? null
)

const prevStatus = computed<ProjectLifecycleStatus | null>(
  () => LIFECYCLE_PREV[props.project.lifecycle_status] ?? null
)

const showTransition = computed(
  () => Boolean(nextStatus.value) && props.canManage
)

const showBackTransition = computed(
  () => Boolean(prevStatus.value) && props.canManage
)

const fromLabel = computed(() => lifecycleLabel(props.project.lifecycle_status))
const toLabel = computed(() => (nextStatus.value ? lifecycleLabel(nextStatus.value) : ''))
const backLabel = computed(() => (prevStatus.value ? lifecycleLabel(prevStatus.value) : ''))

const confirmShow = ref(false)
const transitioning = ref(false)
const backward = ref(false)

const openConfirm = () => {
  backward.value = false
  confirmShow.value = true
}

const openBackConfirm = () => {
  backward.value = true
  confirmShow.value = true
}

const handleConfirm = async () => {
  const target = backward.value ? prevStatus.value : nextStatus.value
  if (!target) return
  transitioning.value = true
  try {
    const updated = await transitionProjectLifecycle(props.project.id, target)
    confirmShow.value = false
    emit('changed', updated)
    ElMessage.success(t('common.success'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.project.transition_failed'), t))
  } finally {
    transitioning.value = false
  }
}
</script>

<template>
  <div class="mgmt-card">
    <h3>{{ $t('management.project.lifecycle_title') }}</h3>

    <div class="mgmt-lifecycle-strip">
      <template v-for="(stage, idx) in stageLabels" :key="stage.status">
        <div
          class="mgmt-lifecycle-stage"
          :class="{
            current: idx === currentIndex,
            past: idx < currentIndex,
            future: idx > currentIndex,
          }"
        >
          <span class="mgmt-lifecycle-stage-badge">
            <LifecycleBadge :status="stage.status" />
          </span>
          <span class="mgmt-lifecycle-stage-label">{{ stage.label }}</span>
        </div>
        <ArrowRight
          v-if="idx < stageLabels.length - 1"
          class="mgmt-lifecycle-arrow"
          :class="{ passed: idx < currentIndex }"
        />
      </template>
    </div>

    <div class="mgmt-lifecycle-actions">
      <button
        v-if="showBackTransition"
        class="btn-secondary"
        @click="openBackConfirm"
      >
        <ArrowLeft class="w-4 h-4" />
        {{ $t('management.project.previous_transition', { target: backLabel }) }}
      </button>
      <button
        v-if="showTransition"
        class="btn-primary"
        @click="openConfirm"
      >
        {{ $t('management.project.next_transition', { target: toLabel }) }}
      </button>
      <span v-else-if="!nextStatus && !prevStatus" class="mgmt-hint">{{ $t('management.project.lifecycle_retired') }}</span>
    </div>

    <ConfirmActionModal
      :show="confirmShow"
      :title="$t('management.project.lifecycle_title')"
      :message="backward
        ? $t('management.project.transition_back_confirm', { from: fromLabel, to: backLabel })
        : $t('management.project.transition_confirm', { from: fromLabel, to: toLabel })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="primary"
      :loading="transitioning"
      @cancel="confirmShow = false"
      @confirm="handleConfirm"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-lifecycle-strip {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin: 0.5rem 0 1rem;
}

.mgmt-lifecycle-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.3rem;
}

.mgmt-lifecycle-stage.past {
  opacity: 0.45;
}

.mgmt-lifecycle-stage.future {
  opacity: 0.7;
}

.mgmt-lifecycle-stage.current {
  transform: scale(1.05);
}

.mgmt-lifecycle-stage-label {
  font-size: 0.72rem;
  color: #64748b;
  font-weight: 600;
}

.mgmt-lifecycle-arrow {
  width: 1rem;
  height: 1rem;
  color: #cbd5e1;
  flex-shrink: 0;
  margin-bottom: 1.2rem;
}

.mgmt-lifecycle-arrow.passed {
  color: var(--color-primary-400);
}

.mgmt-lifecycle-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
