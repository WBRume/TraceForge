<script setup lang="ts">
import { computed } from 'vue'
import { LoaderCircle, TriangleAlert } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type { RequirementPreviewJob } from '@/types/workspaceAssets'

const props = defineProps<{
  job: RequirementPreviewJob
  split?: boolean
}>()

const emit = defineEmits<{
  back: []
  cancel: []
}>()

const { t } = useI18n()

const isFailed = computed(() => props.job.status === 'FAILED' || props.job.status === 'CANCELLED')
const progressWidth = computed(() => `${Math.max(0, Math.min(100, props.job.progress || 0))}%`)
</script>

<template>
  <section class="preview-progress" :class="{ failed: isFailed }">
    <div class="progress-head">
      <span class="progress-icon" aria-hidden="true">
        <TriangleAlert v-if="isFailed" :size="19" />
        <LoaderCircle v-else class="spinning" :size="19" />
      </span>
      <div>
        <h4>
          {{ isFailed
            ? t('workspace_assets.requirements.preview_progress.failed_title')
            : t('workspace_assets.requirements.preview_progress.title') }}
        </h4>
        <p>
          {{ props.split
            ? t('workspace_assets.requirements.preview_progress.split_body')
            : t('workspace_assets.requirements.preview_progress.body') }}
        </p>
      </div>
    </div>

    <div class="progress-track" role="progressbar" :aria-valuenow="props.job.progress" aria-valuemin="0" aria-valuemax="100">
      <span :style="{ width: progressWidth }" />
    </div>

    <dl class="progress-meta">
      <div>
        <dt>{{ t('workspace_assets.requirements.preview_progress.status') }}</dt>
        <dd>{{ props.job.status }}</dd>
      </div>
      <div>
        <dt>{{ t('workspace_assets.requirements.preview_progress.progress') }}</dt>
        <dd>{{ props.job.progress || 0 }}%</dd>
      </div>
      <div>
        <dt>{{ t('workspace_assets.requirements.preview_progress.message') }}</dt>
        <dd>{{ props.job.error || props.job.message || t('workspace_assets.requirements.preview_progress.waiting_message') }}</dd>
      </div>
    </dl>

    <p class="boundary-note">{{ t('workspace_assets.requirements.preview_progress.boundary') }}</p>

    <footer class="progress-footer">
      <button type="button" class="ghost-action" @click="emit('cancel')">
        {{ t('workspace_assets.requirements.actions.close') }}
      </button>
      <button v-if="isFailed && !props.split" type="button" class="secondary-action" @click="emit('back')">
        {{ t('workspace_assets.requirements.actions.back') }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.preview-progress {
  display: grid;
  gap: 14px;
  padding: 18px 22px;
}

.progress-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.progress-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
}

.preview-progress.failed .progress-icon {
  background: #fef2f2;
  color: #dc2626;
}

.spinning {
  animation: spin 1s linear infinite;
}

.progress-head h4 {
  margin: 0 0 5px;
  color: #0f172a;
}

.progress-head p {
  margin: 0;
  color: #64748b;
  line-height: 1.55;
}

.progress-track {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #2563eb;
  transition: width 180ms ease;
}

.preview-progress.failed .progress-track span {
  background: #dc2626;
}

.progress-meta {
  display: grid;
  gap: 8px;
  margin: 0;
}

.progress-meta div {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.progress-meta dt {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.progress-meta dd {
  margin: 0;
  color: #0f172a;
  word-break: break-word;
}

.boundary-note {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  line-height: 1.55;
}

.progress-footer {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.ghost-action,
.secondary-action {
  min-height: 34px;
  padding: 0 13px;
  border-radius: 8px;
  font-weight: 700;
  cursor: pointer;
}

.ghost-action {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
}

.secondary-action {
  border: 1px solid rgba(37, 99, 235, 0.2);
  background: #eff6ff;
  color: #1d4ed8;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 720px) {
  .progress-meta div {
    grid-template-columns: 1fr;
  }
}
</style>
