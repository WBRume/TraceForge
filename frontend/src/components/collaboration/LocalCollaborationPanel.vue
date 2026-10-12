<script setup lang="ts">
import { computed, proxyRefs, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import CodeComparison from './CodeComparison.vue'
import CollaborationTransferStatus from './CollaborationTransferStatus.vue'
import CollaborationBackups from './CollaborationBackups.vue'
import { changedFiles, collaborationFileKey, localFiles, manifestFiles } from '@/composables/collaboration/compare'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import type { CollaborationBackup, CollaborationConflict } from '@/types/collaboration'

const props = defineProps<{ controller: LocalCollaboration; workspaceId: string }>()
const emit = defineEmits<{ history: [] }>()
const { t } = useI18n(), router = useRouter()
const c = computed(() => proxyRefs(props.controller))
const tab = computed({ get: () => c.value.view.tab, set: value => { c.value.view.tab = value } })
const pair = computed({ get: () => c.value.view.pair, set: value => { c.value.view.pair = value } })
const selected = computed({ get: () => c.value.view.selected, set: value => { c.value.view.selected = value } })
watch(() => c.value.driver, driver => { if (driver) pair.value = 'local-cloud' })
watch(() => c.value.local?.manifest, manifest => { if (!manifest && !c.value.driver) { pair.value = 'input-cloud'; if (tab.value === 'local') tab.value = 'cloud' } }, { immediate: true })
const pendingRestore = shallowRef<{ conflicts: CollaborationConflict[]; id: string } | null>(null)
const disableConfirmation = shallowRef(false), backup = shallowRef<CollaborationBackup | null>(null)
const localPaths = computed(() => c.value.local?.local_changes?.map(row => `${c.value.state?.repositories.find(repo => repo.task_repository_id === row.task_repository_id)?.repo_slug || row.task_repository_id}/${row.path}`).join('\n') || '')
const selectedConflicts = computed({ get: () => c.value.view.selectedConflicts, set: value => { c.value.view.selectedConflicts = value } })
const local = computed(() => localFiles(c.value.local))
const cloud = computed(() => manifestFiles(c.value.cloud || c.value.local?.target))
const input = computed(() => manifestFiles(c.value.input || c.value.local?.baseline))
const baseline = computed(() => manifestFiles(c.value.local?.received || c.value.local?.baseline))
const left = computed(() => tab.value === 'local' ? baseline.value : tab.value === 'cloud' || pair.value === 'input-cloud' ? input.value : local.value)
const right = computed(() => tab.value === 'local' ? local.value : cloud.value)
const files = computed(() => {
  const all = tab.value === 'compare' ? new Map([...changedFiles(input.value, cloud.value), ...changedFiles(baseline.value, local.value)].map(file => [file.key, file])) : new Map(changedFiles(left.value, right.value).map(file => [file.key, file]))
  return [...all.values()]
})
const active = computed(() => files.value.find(file => file.key === selected.value))
const leftLabel = computed(() => t(tab.value === 'local' ? 'collaboration.receivedSource' : tab.value === 'cloud' || pair.value === 'input-cloud' ? 'collaboration.inputSource' : 'collaboration.localSource'))
const rightLabel = computed(() => t(tab.value === 'local' ? 'collaboration.localSource' : c.value.cloud?.source === 'PROGRESS' ? 'collaboration.candidateSource' : 'collaboration.finalSource'))
const canEnable = computed(() => c.value.available && !c.value.loading && !c.value.busy && c.value.state?.repositories.length && c.value.state.repositories.every(repo => c.value.mappings[repo.task_repository_id] || c.value.local?.repositories?.some(bound => bound.task_repository_id === repo.task_repository_id && bound.mapped_repo_root)))
const mappingChecks = computed(() => new Map((c.value.mappingChecks || []).map(row => [row.task_repository_id, row])))
const mappingProblem = (problem: string) => problem === 'HEAD_MISMATCH' ? t('collaboration.headMismatch') : problem === 'WORKTREE_DIRTY' ? t('collaboration.worktreeDirty') : problem
const selectedFinalConflicts = computed(() => c.value.conflicts.filter(row => selectedConflicts.value.includes(collaborationFileKey(row.task_repository_id, row.path))))
const restoreDescription = computed(() => pendingRestore.value?.conflicts.map(row => {
  const repo = c.value.local?.repositories?.find(item => item.task_repository_id === row.task_repository_id)
  return `${repo?.local_worktree_path || repo?.repo_slug || row.task_repository_id}/${row.path}${!row.cloud ? ` (${t('collaboration.delete')})` : ''}`
}).join('\n') || '')
watch(files, rows => { if (!rows.some(row => row.key === selected.value)) selected.value = rows[0]?.key || '' }, { immediate: true })
watch(() => c.value.local?.conflict_set_id, () => {
  if (c.value.view.conflictSetId === (c.value.local?.conflict_set_id || '')) return
  c.value.view.conflictSetId = c.value.local?.conflict_set_id || ''
  selectedConflicts.value = c.value.conflicts.map(row => collaborationFileKey(row.task_repository_id, row.path))
  if (c.value.conflicts.length) { tab.value = 'compare'; pair.value = 'local-cloud' }
}, { immediate: true })
function askRestore() {
  if (c.value.local?.conflict_set_id && selectedFinalConflicts.value.length) pendingRestore.value = { conflicts: structuredClone(selectedFinalConflicts.value), id: c.value.local.conflict_set_id }
}
async function confirmRestore() {
  const confirmation = pendingRestore.value
  if (!confirmation) return
  await c.value.restore(confirmation.conflicts, confirmation.id)
  pendingRestore.value = null
}
</script>

<template>
  <section class="collaboration-panel">
    <div class="collaboration-context"><strong role="status">{{ c.label }}</strong><button class="btn-micro" @click="emit('history')">{{ t('collaboration.history') }}</button><button class="btn-micro" :disabled="c.busy" @click="c.refreshComparison">{{ t('collaboration.refresh') }}</button></div>
    <div class="directory-row"><CollaborationTransferStatus :activity="c.activity" /></div>
    <p v-if="c.busy && c.operationStage" class="notice" role="status">{{ t(`collaboration.${c.operationStage}`) }} · {{ t('collaboration.elapsed', { seconds: c.operationSeconds }) }}</p>
    <p v-if="c.error" class="error" role="alert">{{ c.error }}</p>
    <p v-for="problem in c.local?.errors || []" :key="problem" class="error" role="alert">{{ problem }}</p>
    <p v-if="c.state?.recovery_message" class="error" role="alert">{{ c.state.recovery_message }}</p>
    <div v-if="c.phase === 'RECOVERY_REQUIRED' || c.phase === 'STOPPING' || (c.enabled && c.error && !c.preparationRequired)" class="directory-row"><button class="btn-primary" :disabled="c.busy || !c.driver || c.state?.driver_connected === false" @click="c.recover">{{ t('collaboration.recover') }}</button></div>
    <p v-if="!c.available" class="notice">{{ t('collaboration.desktopRequired') }}</p>
    <div v-if="c.available && c.state?.enabled && c.state.driver_connected === false" class="directory-row"><button class="btn-secondary" :disabled="c.busy" @click="c.claimDriver">{{ t('collaboration.claimDriver') }}</button></div>
    <template v-if="!c.enabled || c.phase === 'ENABLING' || (c.driver && (c.preparationRequired || !c.local?.baseline))">
      <div class="activation">
        <h3>{{ t('collaboration.reviewTitle') }}</h3>
        <p>{{ t('collaboration.reviewHint') }}</p>
        <article v-for="repo in c.state?.repositories" :key="repo.task_repository_id" class="repository-check">
          <strong>{{ repo.repo_slug }} <code>{{ repo.branch_name }}</code></strong>
          <small>{{ t('collaboration.base') }} · {{ repo.base_commit_sha }}</small>
          <span>{{ t('collaboration.mapping') }}: {{ c.mappings[repo.task_repository_id]?.local_path || c.local?.repositories?.find(row => row.task_repository_id === repo.task_repository_id)?.mapped_repo_root || t('collaboration.mappingMissing') }}</span>
          <template v-if="mappingChecks.get(repo.task_repository_id)">
            <small>{{ t('collaboration.localHead') }}: {{ mappingChecks.get(repo.task_repository_id)?.local_head || '—' }} · {{ mappingChecks.get(repo.task_repository_id)?.local_branch || '—' }}</small>
            <small v-if="!mappingChecks.get(repo.task_repository_id)?.errors.length">{{ t('collaboration.mappingCheckPassed') }}</small>
            <small v-for="problem in mappingChecks.get(repo.task_repository_id)?.errors" :key="problem" role="alert">{{ mappingProblem(problem) }}</small>
            <pre v-if="mappingChecks.get(repo.task_repository_id)?.changes.length" class="mapping-changes">{{ mappingChecks.get(repo.task_repository_id)?.changes.join('\n') }}</pre>
          </template>
        </article>
        <button class="btn-secondary" @click="router.push(`/workspaces/${workspaceId}/settings`)">{{ t('collaboration.configureMappings') }}</button>
        <p v-if="c.enabled && c.preparationRequired" role="status">{{ t('collaboration.preparationRetryHint') }}</p>
        <button class="btn-primary" :disabled="!canEnable || (c.enabled && (!c.driver || c.state?.driver_connected === false))" @click="c.enabled ? c.recover() : c.enable()">{{ c.busy ? t('collaboration.working') : t(c.enabled ? 'collaboration.recover' : 'collaboration.confirmEnable') }}</button>
        <p>{{ t('collaboration.originalUntouched') }}</p>
      </div>
    </template>
    <template v-else>
      <div v-if="c.driver && c.phase === 'READY'" class="directory-row"><button class="btn-primary" :disabled="c.busy" @click="c.handoffLocalChanges">{{ t('collaboration.handoff') }}</button><button class="btn-micro" :disabled="c.busy" @click="disableConfirmation = true">{{ t('collaboration.disable') }}</button></div>
      <div v-for="repo in c.local?.repositories" :key="repo.task_repository_id" class="directory-row"><span>{{ repo.repo_slug }} · {{ repo.local_worktree_path }}</span><button class="btn-micro" @click="c.openDirectory(repo.task_repository_id)">{{ t('collaboration.openDirectory') }}</button></div>
      <p v-if="!c.driver" class="notice">{{ t(c.remoteSender ? 'collaboration.waitDesktop' : 'collaboration.observer') }}</p>
      <label v-if="c.driver" class="directory-row"><input type="checkbox" :checked="c.progressive" @change="c.setProgressive(($event.target as HTMLInputElement).checked)" />{{ t('collaboration.progressive') }}<small>{{ t('collaboration.progressiveHint') }}</small></label>
      <nav class="comparison-tabs" :aria-label="t('collaboration.views')"><button v-for="name in ['cloud', 'local', 'compare']" :key="name" :class="{ active: tab === name }" :disabled="name === 'local' && !c.local?.manifest" @click="tab = name">{{ t(`collaboration.tabs.${name}`) }}</button></nav>
      <div v-if="tab === 'compare'" class="compare-options"><BaseSelect v-model="pair" size="sm" :options="[{ value: 'local-cloud', label: t('collaboration.localCloud'), disabled: !c.local?.manifest }, { value: 'input-cloud', label: t('collaboration.inputCloud') }]" /><span>{{ t('collaboration.readonly') }}</span></div>
      <template v-if="backup"><button class="btn-micro" @click="backup = null">{{ t('collaboration.back') }}</button><CodeComparison :path="backup.path" :left-hash="backup.sha256 || undefined" :right-hash="local.get(collaborationFileKey(backup.task_repository_id, backup.path))?.sha256" :left-label="t('collaboration.backupSource')" :right-label="t('collaboration.localSource')" :read-text="c.readText" /></template>
      <div v-else-if="files.length" class="file-comparison">
        <aside class="file-navigation">
          <button v-for="file in files" :key="file.key" :class="{ active: selected === file.key }" @click="selected = file.key"><strong>{{ file.repo_slug }}</strong><span>{{ file.path }}</span><small v-if="c.conflicts.some(row => collaborationFileKey(row.task_repository_id, row.path) === file.key)">{{ t('collaboration.conflict') }}</small></button>
        </aside>
        <CodeComparison v-if="active" :path="`${active.repo_slug}/${active.path}`" :left-hash="left.get(active.key)?.sha256" :right-hash="right.get(active.key)?.sha256" :left-label="leftLabel" :right-label="rightLabel" :read-text="c.readText" />
      </div>
      <p v-else class="empty">{{ t('collaboration.noChanges') }}</p>
      <footer v-if="c.phase === 'CONFLICT_PENDING' && c.conflicts.length" class="conflict-actions">
        <strong>{{ t('collaboration.restoreHint') }}</strong>
        <label v-for="row in c.conflicts" :key="collaborationFileKey(row.task_repository_id, row.path)"><input v-model="selectedConflicts" type="checkbox" :value="collaborationFileKey(row.task_repository_id, row.path)" />{{ c.state?.repositories.find(repo => repo.task_repository_id === row.task_repository_id)?.repo_slug }}/{{ row.path }}</label>
        <button class="btn-primary" :disabled="c.busy || !c.driver || !selectedFinalConflicts.length" @click="askRestore">{{ t('collaboration.restoreSelected', { count: selectedFinalConflicts.length }) }}</button>
      </footer>
      <CollaborationBackups v-if="c.driver" :controller="controller" @select="backup = $event" />
    </template>
    <ConfirmActionModal :show="Boolean(pendingRestore)" :title="t('collaboration.restoreTitle')" :message="t('collaboration.backupFirst')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.confirmRestore')" :loading="c.busy" @cancel="pendingRestore = null" @confirm="confirmRestore"><template #content><pre class="restore-paths">{{ restoreDescription }}</pre></template></ConfirmActionModal>
    <ConfirmActionModal :show="disableConfirmation" :title="t('collaboration.disable')" :message="t('collaboration.disableHint')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.disable')" :loading="c.busy" @cancel="disableConfirmation = false" @confirm="async () => { await c.disable(); disableConfirmation = false }"><template #content><pre class="restore-paths">{{ localPaths || t('collaboration.noLocalPending') }}</pre></template></ConfirmActionModal>
  </section>
</template>

<style scoped>
.mapping-changes { max-height: 160px; overflow: auto; font: 11px/1.6 monospace; white-space: pre-wrap; overflow-wrap: anywhere; }.repository-check [role="alert"] { color: #b91c1c; }
.restore-paths { font: 12px/1.7 var(--font-mono,monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.collaboration-panel { flex: 1; display: flex; flex-direction: column; min-height: 0; color: var(--text-primary); }.collaboration-context,.directory-row,.compare-options { display: flex; align-items: center; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--border-color,#e2e8f0); }.collaboration-context strong,.directory-row span { flex: 1; min-width: 0; overflow-wrap: anywhere; }.directory-row { font-size: 12px; }.activation { padding: 18px; overflow: auto; }.activation h3 { margin-bottom: 10px; }.activation p,.repository-check small { color: var(--text-secondary); font-size: 12px; line-height: 1.7; }.activation button { margin: 12px 8px 12px 0; }.repository-check { display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--border-color,#e2e8f0); padding: 16px 0; font-size: 12px; overflow-wrap: anywhere; }.repository-check code { margin-left: 12px; }.notice,.error { margin: 12px 18px; font-size: 12px; }.error { color: #b91c1c; }.comparison-tabs { display: flex; padding: 0 18px; border-bottom: 1px solid var(--border-color,#e2e8f0); }.comparison-tabs button { padding: 12px 16px; border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; }.comparison-tabs button.active { color: var(--primary-color,#2563eb); border-bottom: 2px solid currentColor; }.compare-options { font-size: 11px; }.compare-options :deep(.base-select) { min-width: 160px; }.file-comparison { display: flex; flex: 1; min-height: 0; }.file-navigation { width: 190px; flex-shrink: 0; overflow: auto; border-right: 1px solid var(--border-color,#e2e8f0); }.file-navigation button { display: flex; flex-direction: column; gap: 4px; width: 100%; text-align: left; padding: 12px; border: 0; border-bottom: 1px solid var(--border-color,#e2e8f0); background: transparent; cursor: pointer; font-size: 12px; overflow-wrap: anywhere; }.file-navigation button.active { background: rgba(37,99,235,.08); }.file-navigation small { color: #b45309; }.empty { padding: 32px; text-align: center; color: var(--text-secondary); }.conflict-actions { padding: 14px 18px; display: flex; flex-direction: column; gap: 10px; border-top: 1px solid var(--border-color,#e2e8f0); max-height: 240px; overflow: auto; font-size: 12px; }.conflict-actions label { display: flex; gap: 8px; }.conflict-actions button { align-self: flex-end; }@media(max-width:760px) { .file-navigation { width: 140px; }.compare-options { flex-wrap: wrap; } }
@media (max-width: 600px) {
  .collaboration-context, .directory-row { flex-wrap: wrap; }
  .collaboration-context strong { flex-basis: 100%; }
  .file-comparison { flex-direction: column; min-width: 0; }
  .file-navigation { width: 100%; max-height: 96px; border-right: 0; border-bottom: 1px solid var(--border-color,#e2e8f0); }
  .file-navigation button { flex-direction: row; align-items: center; gap: 8px; padding: 8px 12px; }
  .file-navigation button span { flex: 1; min-width: 0; }
  .comparison-tabs { padding: 0 8px; }.comparison-tabs button { padding: 12px; }
}
</style>
