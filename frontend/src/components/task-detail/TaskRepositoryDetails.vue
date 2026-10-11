<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { TaskRepositoryDetail } from '@/types/taskInspection'

defineProps<{ repositories: TaskRepositoryDetail[] }>()
const { t } = useI18n()
</script>

<template>
  <section class="repository-details">
    <h3 class="section-title">{{ t('task_inspection.repositories') }}</h3>
    <p class="section-hint">{{ t('task_inspection.snapshot_hint') }}</p>
    <p v-if="!repositories.length" class="empty-state">{{ t('task_inspection.no_repositories') }}</p>
    <article v-for="repo in repositories" :key="repo.id" class="repository">
      <header class="repository-heading">
        <h4 class="repository-name">{{ repo.repo_name }}</h4>
        <span class="repository-state" :class="repo.state.toLowerCase()">{{ t(`task_inspection.state_${repo.state.toLowerCase()}`, repo.state) }}</span>
      </header>
      <dl class="repository-fields">
        <dt>{{ t('task_inspection.repo_url') }}</dt><dd class="mono">{{ repo.repo_url }}</dd>
        <dt>{{ t('task_inspection.source_branch') }}</dt><dd class="mono">{{ repo.branch_name || t('task_inspection.not_recorded') }}</dd>
        <dt>{{ t('task_inspection.initial_head') }}</dt>
        <dd class="mono">{{ repo.base_commit_sha || t(repo.state === 'PENDING' ? 'task_inspection.checkout_pending' : 'task_inspection.not_recorded') }}</dd>
        <dt>{{ t('task_inspection.task_branch') }}</dt><dd class="mono">{{ repo.task_branch || t('task_inspection.not_recorded') }}</dd>
        <dt>{{ t('task_inspection.worktree_path') }}</dt><dd class="mono">{{ repo.worktree_path || repo.rel_path }}</dd>
        <template v-if="repo.base_commit">
          <dt>{{ t('task_inspection.author') }}</dt><dd>{{ repo.base_commit.author_name }} &lt;{{ repo.base_commit.author_email }}&gt;</dd>
          <dt>{{ t('task_inspection.authored_at') }}</dt><dd>{{ repo.base_commit.authored_at }}</dd>
          <dt>{{ t('task_inspection.committer') }}</dt><dd>{{ repo.base_commit.committer_name }} &lt;{{ repo.base_commit.committer_email }}&gt;</dd>
          <dt>{{ t('task_inspection.committed_at') }}</dt><dd>{{ repo.base_commit.committed_at }}</dd>
          <dt>{{ t('task_inspection.commit_message') }}</dt><dd class="commit-message">{{ repo.base_commit.message || t('task_inspection.empty_message') }}</dd>
        </template>
      </dl>
      <p v-if="repo.base_commit_sha && !repo.base_commit" class="section-hint">{{ t('task_inspection.commit_unavailable') }}</p>
      <p v-else-if="!repo.base_commit_sha && repo.state !== 'PENDING'" class="section-hint">{{ t('task_inspection.history_unavailable') }}</p>
      <p v-if="repo.error_message" class="error-message">{{ repo.error_message }}</p>
    </article>
  </section>
</template>

<style scoped>
.repository-details { min-width: 0; }
.section-title { margin: 0; font-size: 15px; color: var(--color-text-main, #1e293b); }
.section-hint, .empty-state { color: var(--color-text-muted, #64748b); font-size: 12px; line-height: 1.6; margin: 8px 0 12px; }
.repository { padding: 16px 0; border-top: 1px solid var(--color-border, #e2e8f0); }
.repository:last-child { padding-bottom: 0; }
.repository-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.repository-name { margin: 0; font-size: 14px; overflow-wrap: anywhere; }
.repository-state { flex-shrink: 0; font-size: 11px; padding: 2px 8px; border-radius: 6px; background: #f1f5f9; color: #64748b; }
.repository-state.ready { background: #ecfdf5; color: #047857; }
.repository-state.failed { background: #fef2f2; color: #b91c1c; }
.repository-fields { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 10px 16px; font-size: 13px; line-height: 1.6; margin: 0; }
.repository-fields dt { color: var(--color-text-muted, #64748b); }
.repository-fields dd { margin: 0; overflow-wrap: anywhere; user-select: text; }
.mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: 12px; }
.commit-message { white-space: pre-wrap; }
.error-message { color: #b91c1c; font-size: 12px; overflow-wrap: anywhere; }
@media (max-width: 560px) {
  .repository-fields { grid-template-columns: minmax(0, 1fr); gap: 3px; }
  .repository-fields dd { margin-bottom: 10px; }
}
</style>
