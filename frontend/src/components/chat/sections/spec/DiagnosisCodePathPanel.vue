<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { GitFork, Loader2 } from 'lucide-vue-next'
import type { DiagnosisDocsModelView } from '@/composables/useDiagnosisDocs'

/**
 * 问题定位任务：代码路径面板（任务 project_path + 工作区关联仓库清单）。
 */
const props = defineProps<{
  model: DiagnosisDocsModelView
}>()

const { t } = useI18n()
</script>

<template>
  <div class="diag-panel">
    <header class="diag-panel-header">
      <div class="diag-panel-title-group">
        <div class="diag-panel-title-line">
          <div class="diag-panel-title-icon amber">
            <GitFork :size="18" :stroke-width="2.5" />
          </div>
          <span>{{ t('diagnosis.code_path_tab') }}</span>
        </div>
        <p class="diag-panel-subtitle">{{ t('diagnosis.code_path_label') }}</p>
      </div>
    </header>

    <div class="diag-body diag-body-stack">
      <section class="diag-section">
        <h4 class="diag-section-label">{{ t('diagnosis.code_path_label') }}</h4>
        <pre v-if="props.model.codePath" class="diag-code-path">{{ props.model.codePath }}</pre>
        <div v-else-if="props.model.reposLoading" class="diag-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else class="diag-state">{{ t('diagnosis.code_path_empty') }}</div>
      </section>

      <section class="diag-section">
        <h4 class="diag-section-label">{{ t('diagnosis.repo_list_label') }}</h4>
        <div v-if="props.model.reposLoading" class="diag-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else-if="props.model.repos.length === 0" class="diag-state">{{ t('diagnosis.repo_list_empty') }}</div>
        <div v-else class="diag-repo-list">
          <div v-for="repo in props.model.repos" :key="repo.id || repo.repo_name" class="diag-repo-item">
            <div class="diag-doc-icon-container blue">
              <GitFork :size="14" :stroke-width="2.5" />
            </div>
            <div class="diag-repo-body">
              <div class="diag-repo-name">
                {{ repo.repo_name }}
                <span v-if="repo.state" class="diag-repo-state">{{ repo.state }}</span>
              </div>
              <div class="diag-repo-meta">
                {{ [repo.branch_name, repo.repo_url].filter(Boolean).join(' · ') }}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped src="./diagnosis-panel.css"></style>
<style scoped>
.diag-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.diag-section-label {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.diag-code-path {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: var(--radius-lg);
  background: #ffffff;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--color-text-body);
  overflow: auto;
  word-break: break-all;
  box-shadow: var(--shadow-sm);
}

.diag-repo-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.diag-repo-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: #ffffff;
  box-shadow: var(--shadow-sm);
}

.diag-repo-body {
  min-width: 0;
  flex: 1;
}

.diag-repo-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-title);
}

.diag-repo-state {
  padding: 0 6px;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--color-text-muted);
  background: var(--color-bg-base);
}

.diag-repo-meta {
  margin-top: 2px;
  font-size: 0.68rem;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diag-doc-icon-container {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
}

.diag-doc-icon-container.blue {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
</style>
