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
const allChecked = computed(() => allMapped.value && repos.value.every(repo => repo.check && !repo.check.errors.length))
const checkFailed = computed(() => repos.value.some(repo => repo.check?.errors.length))
const canPrepare = computed(() => c.value.available && (!c.value.enabled || (c.value.driver && c.value.state?.driver_connected !== false)))
const problemText = (code: string) => t(code === 'HEAD_MISMATCH' ? 'collaboration.headMismatch' : code === 'WORKTREE_DIRTY' ? 'collaboration.worktreeDirty' : 'collaboration.ui.repoCheckError', { code })
// One read-only preflight on entering setup, never a repeating full-workspace verification.
watch(() => props.setup && allMapped.value && canPrepare.value && !c.value.loading, ready => {
  if (ready && !c.value.busy && !c.value.mappingChecks.length) void c.value.checkMappings()
}, { immediate: true })
async function connect() {
  if (!allChecked.value) { await c.value.checkMappings(); return }
  if (c.value.enabled) await c.value.recover()
  else await c.value.enable()
}
</script>

<template>
  <section class="repository-settings">
    <h2>{{ t(setup ? 'collaboration.ui.connectTitle' : 'collaboration.ui.settings') }}</h2>
    <p class="intro">{{ t(setup ? 'collaboration.ui.connectHint' : 'collaboration.ui.settingsHint') }}</p>
    <div class="repositories">
      <article v-for="repo in repos" :key="repo.task_repository_id">
        <div class="repo-heading"><strong>{{ repo.repo_slug }}</strong><code>{{ repo.branch_name }}</code><span v-if="setup" :class="{ warning: repo.check?.errors.length }">{{ t(!repo.path ? 'collaboration.ui.mappingMissing' : repo.check?.errors.length ? 'collaboration.ui.checkFailed' : repo.check ? 'collaboration.ui.checkPassed' : 'collaboration.ui.notChecked') }}</span></div>
        <div class="repo-path"><span :title="repo.path">{{ repo.path || t(setup ? 'collaboration.ui.chooseDirectory' : 'collaboration.ui.localUnavailable') }}</span><button v-if="setup && canPrepare" class="text-action" type="button" :disabled="c.busy" @click="c.selectMapping(repo.task_repository_id)">{{ t(repo.path ? 'collaboration.ui.changeDirectory' : 'collaboration.ui.chooseDirectory') }}</button><button v-else-if="ui?.localAvailable" class="text-action" type="button" @click="c.openDirectory(repo.task_repository_id)">{{ t('collaboration.ui.openDirectory') }}</button></div>
        <details class="check-details"><summary>{{ t('collaboration.ui.taskBaseline') }} <code>{{ repo.base_commit_sha.slice(0, 8) }}</code><span v-if="repo.check && !repo.check.errors.length && setup"> · {{ t('collaboration.ui.cleanHead') }}</span></summary><p>{{ t('collaboration.base') }}: {{ repo.base_commit_sha }}</p><p v-if="setup && repo.check">{{ t('collaboration.localHead') }}: {{ repo.check.local_head }} · {{ repo.check.local_branch }}</p><pre v-if="setup && repo.check?.changes.length">{{ repo.check.changes.join('\n') }}</pre></details>
        <p v-for="problem in setup ? repo.check?.errors || [] : []" :key="problem" class="repo-error" role="alert">{{ problemText(problem) }}</p>
      </article>
    </div>
    <div v-if="setup" class="setup-actions"><small>{{ t(c.available ? 'collaboration.ui.mappingReuse' : 'collaboration.desktopRequired') }}</small><button v-if="canPrepare" class="btn-primary" type="button" :disabled="c.busy || c.loading || !allMapped" @click="connect">{{ c.busy ? t('collaboration.working') : t(allChecked ? 'collaboration.ui.connectRepos' : checkFailed ? 'collaboration.ui.recheck' : 'collaboration.ui.checkRepos', { count: repos.length }) }}</button></div>
    <template v-else>
      <label v-if="c.driver && c.available" class="setting"><span>{{ t('collaboration.ui.autoReceive') }}<small>{{ t('collaboration.ui.autoReceiveHint') }}</small></span><input type="checkbox" :checked="c.progressive" :disabled="c.busy" @change="c.setProgressive(($event.target as HTMLInputElement).checked)" /></label>
      <div class="setting"><span>{{ t('collaboration.ui.device') }}<small>{{ t(c.state?.driver_connected === false ? 'collaboration.ui.deviceOffline' : c.driver ? 'collaboration.ui.thisDevice' : 'collaboration.ui.otherDevice') }}</small></span><button v-if="c.available && !c.driver" class="text-action" type="button" @click="emit('device')">{{ t('collaboration.ui.deviceDetails') }}</button></div>
      <p v-if="c.state?.driver_connected === false && !c.canReconnect" class="intro">{{ t('collaboration.ui.reconnectElsewhereHint') }}</p>
    </template>
  </section>
</template>

<style scoped>
.repository-settings { padding: 28px 24px; overflow: auto; }.repository-settings h2 { margin: 0; font-size: 19px; font-weight: 600; }.intro { margin: 8px 0 24px; color: var(--color-text-muted); font-size: 12px; line-height: 1.8; }.repositories { border-top: 1px solid #e5eaf0; }.repositories article { padding: 18px 0; border-bottom: 1px solid #e5eaf0; }.repo-heading { display: flex; align-items: center; gap: 12px; font-size: 13px; }.repo-heading code { font-size: 11px; color: var(--color-text-muted); overflow-wrap: anywhere; }.repo-heading>span { margin-left: auto; color: #278267; font-size: 11px; flex-shrink: 0; }.repo-heading>span.warning { color: #a66a12; }.repo-path { display: flex; gap: 12px; align-items: flex-start; margin-top: 8px; font-size: 12px; }.repo-path>span { flex: 1; min-width: 0; overflow-wrap: anywhere; color: var(--color-text-muted); }.text-action { border: 0; background: none; color: var(--color-primary-600); font: inherit; font-size: 12px; padding: 0; cursor: pointer; flex-shrink: 0; }.text-action:disabled { opacity: .5; cursor: default; }.check-details { margin-top: 8px; font-size: 11px; color: var(--color-text-muted); }.check-details summary { cursor: pointer; }.check-details p { overflow-wrap: anywhere; margin: 8px 0; }.check-details pre { max-height: 130px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }.repo-error { color: #a66a12; font-size: 12px; margin: 8px 0 0; }.setup-actions { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 24px; }.setup-actions small { color: var(--color-text-muted); font-size: 11px; }.setup-actions button { flex-shrink: 0; }.setting { display: flex; gap: 20px; justify-content: space-between; padding: 20px 0; border-bottom: 1px solid #e5eaf0; font-size: 12px; }.setting small { display: block; color: var(--color-text-muted); margin-top: 4px; }.setting input { accent-color: var(--color-primary-600); }
@media(max-width:600px) { .repository-settings { padding: 20px 16px; }.setup-actions { flex-wrap: wrap; }.repo-path { flex-wrap: wrap; }.repo-path>span { flex-basis: 100%; } }
</style>
