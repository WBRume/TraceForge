<script setup lang="ts">
import { computed, proxyRefs, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import { useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
const props = defineProps<{ controller: LocalCollaboration; setup: boolean }>()
const emit = defineEmits<{ device: [] }>()
const { t } = useI18n()
const c = computed(() => proxyRefs(props.controller))
const ui = useCollaborationPresentation(() => props.controller)
const repos = computed(() => (c.value.state?.repositories || []).map(repo => ({ ...repo,
  path: (props.setup ? c.value.mappings[repo.task_repository_id]?.local_path : c.value.local?.repositories?.find(row => row.task_repository_id === repo.task_repository_id)?.local_worktree_path) || '',
  check: c.value.mappingChecks.find(row => row.task_repository_id === repo.task_repository_id),
})))
const allMapped = computed(() => repos.value.length > 0 && repos.value.every(repo => repo.path))
const resumable = computed(() => Boolean(c.value.local?.baseline && (!c.value.local.released || c.value.local.suspended)))
const canPrepare = computed(() => c.value.available && (!c.value.participating || c.value.driver))
const problemText = (code: string) => t(code === 'HEAD_MISMATCH' ? 'collaboration.headMismatch' : code === 'WORKTREE_DIRTY' ? 'collaboration.worktreeDirty' : 'collaboration.ui.repoCheckError', { code })
// One read-only preflight on entering setup, never a repeating full-workspace verification.
watch(() => props.setup && allMapped.value && canPrepare.value && !c.value.loading, ready => {
  if (ready && !c.value.busy && !c.value.mappingChecks.length) void c.value.checkMappings()
}, { immediate: true })
async function connect() {
  if (c.value.participating) await c.value.recover()
  else await c.value.enable()
}
</script>

<template>
  <section class="repository-settings">
    <h2>{{ t(setup ? 'collaboration.ui.connectTitle' : 'collaboration.ui.settings') }}</h2>
    <p class="intro">{{ t(setup ? resumable ? 'collaboration.session.resumeHint' : 'collaboration.ui.connectHint' : 'collaboration.ui.settingsHint') }}</p>
    <div class="repositories">
      <article v-for="repo in repos" :key="repo.task_repository_id" class="repo-card-item">
        <div class="repo-heading">
          <strong>{{ repo.repo_slug }}</strong>
          <code class="branch-pill">{{ repo.branch_name }}</code>
          <span v-if="setup" class="check-status-tag" :class="{ warning: repo.check?.errors.length }">
            {{ t(!repo.path ? 'collaboration.ui.mappingMissing' : repo.check?.errors.length ? 'collaboration.ui.checkFailed' : resumable ? 'collaboration.session.resumeBaseline' : repo.check ? 'collaboration.ui.checkPassed' : 'collaboration.ui.notChecked') }}
          </span>
        </div>
        <div class="repo-path">
          <span :title="repo.path" class="path-text">{{ repo.path || t(setup ? 'collaboration.ui.chooseDirectory' : 'collaboration.ui.localUnavailable') }}</span>
          <button v-if="setup && canPrepare" class="text-action" type="button" :disabled="c.busy" @click="c.selectMapping(repo.task_repository_id)">
            {{ t(repo.path ? 'collaboration.ui.changeDirectory' : 'collaboration.ui.chooseDirectory') }}
          </button>
          <button v-else-if="ui?.localAvailable" class="text-action" type="button" @click="c.openDirectory(repo.task_repository_id)">
            {{ t('collaboration.ui.openDirectory') }}
          </button>
        </div>
        <details class="check-details">
          <summary>{{ t('collaboration.ui.taskBaseline') }} <code>{{ repo.base_commit_sha.slice(0, 8) }}</code><span v-if="repo.check && !repo.check.errors.length && setup"> · {{ t('collaboration.ui.cleanHead') }}</span></summary>
          <p>{{ t('collaboration.base') }}: {{ repo.base_commit_sha }}</p>
          <p v-if="setup && repo.check">{{ t('collaboration.localHead') }}: {{ repo.check.local_head }} · {{ repo.check.local_branch }}</p>
          <pre v-if="setup && repo.check?.changes.length">{{ repo.check.changes.join('\n') }}</pre>
        </details>
        <p v-for="problem in setup ? repo.check?.errors || [] : []" :key="problem" class="repo-error" role="alert">{{ problemText(problem) }}</p>
      </article>
    </div>
    <div v-if="setup" class="setup-actions">
      <small>{{ t(c.available ? 'collaboration.session.choiceHint' : 'collaboration.desktopRequired') }}</small>
      <div class="setup-buttons">
        <button v-if="canPrepare && !c.participating" class="btn-secondary" type="button" :disabled="c.busy || c.loading || !allMapped" @click="c.receiveOnce()">{{ t('collaboration.session.receive') }}</button>
        <button v-if="canPrepare" class="btn-primary" type="button" :disabled="c.busy || c.loading || !allMapped || c.enabled && !c.participating && !c.canReconnect" @click="connect">{{ t(c.participating ? 'collaboration.ui.actions.recover' : 'collaboration.session.connect') }}</button>
      </div>
    </div>
    <template v-else>
      <label v-if="c.participating && c.driver && c.available" class="setting"><span>{{ t('collaboration.ui.autoReceive') }}<small>{{ t('collaboration.ui.autoReceiveHint') }}</small></span><input type="checkbox" :checked="c.progressive" :disabled="c.busy" @change="c.setProgressive(($event.target as HTMLInputElement).checked)" /></label>
      <div class="setting"><span>{{ t('collaboration.ui.device') }}<small>{{ t(c.state?.driver_connected === false ? 'collaboration.ui.deviceOffline' : c.driver ? 'collaboration.ui.thisDevice' : 'collaboration.ui.otherDevice') }}</small></span><button v-if="c.available && !c.driver" class="text-action" type="button" @click="emit('device')">{{ t('collaboration.ui.deviceDetails') }}</button></div>
      <p v-if="c.state?.driver_connected === false && !c.canReconnect" class="intro">{{ t('collaboration.ui.reconnectElsewhereHint') }}</p>
    </template>
  </section>
</template>

<style scoped>
.repository-settings { padding: 20px 24px; overflow-y: auto; background: var(--color-bg-base, #f8fafc); flex: 1; }
.repository-settings h2 { margin: 0; font-size: 15px; font-weight: 600; color: var(--color-text-title, #0f172a); }
.intro { margin: 4px 0 16px; color: var(--color-text-muted, #64748b); font-size: 12px; line-height: 1.6; }

.repositories { display: flex; flex-direction: column; gap: 12px; }
.repo-card-item {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}

.repo-heading { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
.repo-heading strong { font-weight: 600; color: var(--color-text-title, #0f172a); }
.branch-pill {
  font-size: 10.5px;
  color: var(--color-text-muted, #64748b);
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
  font-family: var(--font-mono, monospace);
  overflow-wrap: anywhere;
}
.check-status-tag {
  margin-left: auto;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #d1fae5;
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
  flex-shrink: 0;
}
.check-status-tag.warning {
  color: #b45309;
  background: #fef3c7;
  border-color: #fde68a;
}

.repo-path {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  font-size: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 12px;
}
.path-text {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--color-text-body, #334155);
  font-family: var(--font-mono, monospace);
  font-size: 11.5px;
}
.text-action {
  border: 0;
  background: none;
  color: var(--color-primary-600, #0284c7);
  font: inherit;
  font-size: 11.5px;
  font-weight: 500;
  padding: 0;
  cursor: pointer;
  flex-shrink: 0;
}
.text-action:hover { text-decoration: underline; }
.text-action:disabled { opacity: .5; cursor: default; }

.check-details { margin-top: 10px; font-size: 11px; color: var(--color-text-muted, #64748b); }
.check-details summary { cursor: pointer; }
.check-details p { overflow-wrap: anywhere; margin: 6px 0; }
.check-details pre { max-height: 120px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: #f1f5f9; padding: 6px 10px; border-radius: 4px; }
.repo-error { color: #dc2626; font-size: 11.5px; margin: 6px 0 0; }

.setup-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}
.setup-actions small { color: var(--color-text-muted, #64748b); font-size: 11px; }
.setup-buttons { display: flex; gap: 10px; flex-shrink: 0; }

.setting {
  display: flex;
  gap: 20px;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12.5px;
}
.setting small { display: block; color: var(--color-text-muted, #64748b); margin-top: 3px; font-size: 11px; }
.setting input { accent-color: var(--color-primary-600, #0284c7); cursor: pointer; }

@media(max-width:600px) {
  .repository-settings { padding: 16px; }
  .setup-actions { flex-wrap: wrap; }
  .repo-path { flex-wrap: wrap; }
  .repo-path > span { flex-basis: 100%; }
}
</style>
