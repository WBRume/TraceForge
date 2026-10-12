<script setup lang="ts">
import { computed, proxyRefs, shallowRef, toRaw, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, Check, GitPullRequest, Loader2 } from '@/components/icons'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import CodeComparison from './CodeComparison.vue'
import CollaborationTransferStatus from './CollaborationTransferStatus.vue'
import CollaborationBackups from './CollaborationBackups.vue'
import CollaborationRepositories from './CollaborationRepositories.vue'
import CollaborationFiles from './CollaborationFiles.vue'
import { collaborationFileKey } from '@/composables/collaboration/compare'
import { collaborationReview } from '@/composables/collaboration/review'
import { useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import type { CollaborationBackup, CollaborationConflict } from '@/types/collaboration'

const props = defineProps<{ controller: LocalCollaboration; workspaceId: string }>()
const { t } = useI18n()
const c = computed(() => proxyRefs(props.controller))
const ui = useCollaborationPresentation(() => props.controller)
const downloadOnly = computed(() => c.value.receivedOnce && !c.value.participating)
const tab = computed({ get: () => c.value.view.tab, set: value => { c.value.view.tab = value } })
const pair = computed({ get: () => c.value.view.pair, set: value => { c.value.view.pair = value } })
const selected = computed({ get: () => c.value.view.selected, set: value => { c.value.view.selected = value } })
const checked = computed({ get: () => c.value.view.selectedConflicts, set: value => { c.value.view.selectedConflicts = value } })
const review = computed(() => collaborationReview(c.value, Boolean(ui.value?.localAvailable)))
const files = computed(() => review.value.files.filter(file => tab.value === 'all' || file.kind === tab.value))
const active = computed(() => files.value.find(file => file.key === selected.value))
const filters = computed(() => ['all', 'cloud', 'local', ...(ui.value?.conflicts ? ['conflicts'] : [])].map(value => ({
  value, count: value === 'local' && !ui.value?.localAvailable ? '—' : value === 'all' ? review.value.files.length : review.value.files.filter(file => file.kind === value).length,
})))
const backup = shallowRef<CollaborationBackup | null>(null)
const pendingRestore = shallowRef<{ conflicts: CollaborationConflict[]; id: string } | null>(null)
const deviceConfirmation = shallowRef(false)
const selectedConflicts = computed(() => c.value.conflicts.filter(file => checked.value.includes(collaborationFileKey(file.task_repository_id, file.path))))
const allChecked = computed(() => c.value.conflicts.length > 0 && selectedConflicts.value.length === c.value.conflicts.length)
const comparison = computed(() => {
  const file = active.value
  const localPair = pair.value === 'local-cloud' && ui.value?.localAvailable
  const left = localPair ? review.value.local.get(file?.key || '') : pair.value === 'input-cloud' ? review.value.input.get(file?.key || '') : file?.left
  const right = pair.value !== 'auto' ? review.value.cloud.get(file?.key || '') : file?.right
  const leftSource = localPair || (pair.value === 'auto' && file?.kind === 'conflicts' && ui.value?.localAvailable) ? 'localSource' : pair.value === 'auto' && file?.kind === 'local' ? 'receivedSource' : downloadOnly.value ? 'session.beforeReceive' : 'inputSource'
  const rightSource = pair.value === 'auto' && file?.kind === 'local' ? 'localSource' : downloadOnly.value ? 'session.publishedSource' : ui.value?.running ? 'candidateSource' : 'finalSource'
  return { left, right, leftLabel: t(`collaboration.${leftSource}`), rightLabel: t(`collaboration.${rightSource}`) }
})
const errors = computed(() => [...new Set([c.value.error, ...c.value.local?.errors || [], c.value.state?.recovery_message].filter((value): value is string => Boolean(value)
  && !(ui.value?.setup && [t('collaboration.preparationRequired'), t('collaboration.mappingCheckFailed')].includes(value!))))])
const restoreDescription = computed(() => pendingRestore.value?.conflicts.map(row => {
  const repo = c.value.state?.repositories.find(item => item.task_repository_id === row.task_repository_id)
  return `${repo?.repo_slug || row.task_repository_id}/${row.path}${!row.cloud ? ` · ${t('collaboration.delete')}` : ''}`
}).join('\n') || '')
const canReconnect = computed(() => c.value.canReconnect)
const deviceHint = computed(() => c.value.state?.driver_connected === false ? canReconnect.value ? 'reconnectHint' : 'reconnectElsewhereHint' : 'activeDeviceHint')

watch(files, rows => { if (!rows.some(row => row.key === selected.value)) selected.value = rows[0]?.key || '' }, { immediate: true })
watch(() => [c.value.local?.conflict_set_id, c.value.conflicts] as const, () => {
  const current = c.value.local?.conflict_set_id || ''
  if (c.value.view.conflictSetId !== current) { c.value.view.conflictSetId = current; checked.value = [] }
  else checked.value = checked.value.filter(key => c.value.conflicts.some(row => collaborationFileKey(row.task_repository_id, row.path) === key))
  if (!c.value.conflicts.length && tab.value === 'conflicts') tab.value = ui.value?.localCount ? 'local' : 'all'
}, { immediate: true })
watch(() => ui.value?.localAvailable, available => { if (!available) { if (tab.value === 'local') tab.value = 'all'; if (pair.value === 'local-cloud') pair.value = 'auto' } })
watch(() => c.value.view.page, () => { backup.value = null })
function checkFile(key: string, value: boolean) { checked.value = value ? [...new Set([...checked.value, key])] : checked.value.filter(item => item !== key) }
function askRestore() {
  if (!ui.value?.canRestore || !c.value.local?.conflict_set_id || !selectedConflicts.value.length) return
  pendingRestore.value = { conflicts: structuredClone(selectedConflicts.value.map(row => toRaw(row))), id: c.value.local.conflict_set_id }
}
async function confirmRestore() {
  const confirmation = pendingRestore.value
  if (!confirmation || !ui.value?.canRestore) return
  await c.value.restore(confirmation.conflicts, confirmation.id)
  pendingRestore.value = null
}
async function primaryAction() {
  if (ui.value?.action === 'device') c.value.view.page = 'settings'
  else if (ui.value?.action === 'reconnect') await c.value.claimDriver()
  else if (ui.value?.action === 'recover') await c.value.recover()
}
</script>

<template>
  <section v-if="ui" class="collaboration-panel">
    <ConfirmActionModal :show="c.view.page === 'disconnect'" tone="primary" :title="t('collaboration.session.disconnect')" :message="t('collaboration.session.leaveHint')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.session.disconnect')" :loading="c.busy || c.leaving" @cancel="c.view.page = 'files'" @confirm="async () => { if (await c.leave()) c.view.page = 'files' }" />
    <template v-if="c.view.page === 'settings'">
      <CollaborationRepositories :controller="controller" :setup="false" @device="deviceConfirmation = true" />
    </template>
    <template v-else-if="c.view.page === 'backups'">
      <template v-if="backup"><button class="back-button" type="button" @click="backup = null">{{ t('collaboration.ui.backToBackups') }}</button><CodeComparison :path="backup.path" :left-hash="backup.sha256 || undefined" :right-hash="review.local.get(collaborationFileKey(backup.task_repository_id, backup.path))?.sha256" :left-label="t('collaboration.backupSource')" :right-label="t('collaboration.localSource')" :read-text="c.readText" /></template>
      <CollaborationBackups v-else :controller="controller" @select="backup = $event" />
    </template>
    <template v-else>
      <div v-if="!ui.setup || c.busy || c.loading" class="state-strip" :class="ui.tone">
        <span class="state-icon"><Loader2 v-if="c.busy || ['loading', 'running', 'preparing', 'transferring'].includes(ui.key)" :size="18" class="spin" /><AlertTriangle v-else-if="ui.tone === 'warning'" :size="18" /><Check v-else :size="18" /></span>
        <div class="state-copy"><strong role="status">{{ ui.title }}</strong><p>{{ ui.description }}</p><CollaborationTransferStatus v-if="c.busy && c.activity.total > 0" :activity="c.activity" /><small v-if="c.busy && c.operationStage">{{ t(`collaboration.${c.operationStage}`) }} · {{ t('collaboration.elapsed', { seconds: c.operationSeconds }) }}</small></div>
        <button v-if="ui.action !== 'none' && ui.action !== 'connect' && !c.busy" type="button" :class="ui.action === 'device' ? 'btn-secondary' : 'btn-primary'" @click="primaryAction">{{ ui.actionLabel }}</button>
      </div>
      <details v-if="errors.length" class="error-details" :open="ui.setup"><summary>{{ t('collaboration.ui.errorDetails') }}</summary><p v-for="problem in errors" :key="problem" role="alert">{{ problem }}</p></details>
      <div v-if="!c.participating && c.available && !ui.setup" class="session-actions">
        <button class="btn-secondary" type="button" :disabled="c.busy" @click="c.receiveOnce()">{{ t('collaboration.session.receive') }}</button>
        <button class="btn-primary" type="button" :disabled="c.busy || c.enabled && !c.canReconnect" @click="c.enable()">{{ t('collaboration.session.connect') }}</button>
      </div>
      <CollaborationRepositories v-if="ui.setup" :controller="controller" :setup="true" />
      <template v-else>
        <nav class="file-filters" :aria-label="t('collaboration.ui.fileSources')"><button v-for="item in filters" :key="item.value" type="button" :class="{ active: tab === item.value }" :aria-pressed="tab === item.value" :disabled="item.value === 'local' && !ui.localAvailable" :title="item.value === 'local' && !ui.localAvailable ? t('collaboration.ui.localUnavailable') : ''" @click="tab = item.value"><span>{{ t(downloadOnly && item.value === 'cloud' ? 'collaboration.session.cloudChanges' : `collaboration.ui.filters.${item.value}`) }}</span><small>{{ item.count }}</small></button><span class="scope-label">{{ t(downloadOnly ? 'collaboration.session.receiveScope' : 'collaboration.ui.thisRound') }}</span></nav>
        <div v-if="files.length" class="file-comparison">
          <CollaborationFiles :files="files" :repositories="c.state?.repositories || []" :selected="selected" :checked="checked" :can-restore="ui.canRestore" :local-available="ui.localAvailable" :running="ui.running" @select="selected = $event; pair = 'auto'" @check="checkFile" />
          <div v-if="active" class="diff-workspace">
            <CodeComparison :path="`${active.repo_slug}/${active.path}`" :left-hash="comparison.left?.sha256" :right-hash="comparison.right?.sha256" :left-label="comparison.leftLabel" :right-label="comparison.rightLabel" :read-text="c.readText">
              <template #tools><BaseSelect v-model="pair" size="sm" :aria-label="t('collaboration.ui.compareVersions')" :options="[{ value: 'auto', label: t('collaboration.ui.defaultComparison') }, { value: 'local-cloud', label: t('collaboration.localCloud'), disabled: !ui.localAvailable }, { value: 'input-cloud', label: t('collaboration.inputCloud') }]" /></template>
            </CodeComparison>
            <p class="diff-note">{{ t(active.kind === 'conflicts' ? ui.running ? 'collaboration.ui.previewConflictHint' : 'collaboration.ui.restoreNotice' : active.kind === 'local' ? 'collaboration.ui.localNotice' : ui.running ? 'collaboration.ui.runningNotice' : 'collaboration.ui.agentNotice') }}<span v-if="comparison.left?.mode !== comparison.right?.mode"> · {{ t('collaboration.ui.fileMode') }} {{ comparison.left?.mode || '—' }} → {{ comparison.right?.mode || '—' }}</span></p>
          </div>
        </div>
        <div v-else class="empty-state"><GitPullRequest :size="30" /><strong>{{ t(!review.cloudKnown && tab !== 'local' ? 'collaboration.ui.loadingFiles' : tab === 'local' ? 'collaboration.ui.noLocalChanges' : downloadOnly ? 'collaboration.session.noChanges' : 'collaboration.ui.noAgentChanges') }}</strong><p>{{ t(tab === 'local' ? 'collaboration.ui.noLocalHint' : downloadOnly ? 'collaboration.session.noChangesHint' : 'collaboration.ui.noAgentHint') }}</p></div>
        <footer v-if="ui.canRestore && c.conflicts.length" class="conflict-actions">
          <div><label><input type="checkbox" :checked="allChecked" @change="checked = ($event.target as HTMLInputElement).checked ? c.conflicts.map(row => collaborationFileKey(row.task_repository_id, row.path)) : []" />{{ t('collaboration.ui.selectAllConflicts') }}</label><small>{{ t('collaboration.ui.selectedCount', { count: selectedConflicts.length, total: c.conflicts.length }) }}</small></div>
          <button class="btn-primary" type="button" :disabled="!selectedConflicts.length" @click="askRestore">{{ t('collaboration.restoreSelected', { count: selectedConflicts.length }) }}</button>
        </footer>
      </template>
    </template>
    <ConfirmActionModal :show="Boolean(pendingRestore)" :title="t('collaboration.restoreTitle', { count: pendingRestore?.conflicts.length || 0 })" :message="t('collaboration.backupFirst')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.confirmRestore')" :loading="c.busy" @cancel="pendingRestore = null" @confirm="confirmRestore"><template #content><pre class="restore-paths">{{ restoreDescription }}</pre></template></ConfirmActionModal>
    <ConfirmActionModal :show="c.view.page === 'disable'" :title="t('collaboration.disable')" :message="t('collaboration.disableHint')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.disable')" :loading="c.busy" @cancel="c.view.page = 'files'" @confirm="async () => { await c.disable(); c.view.page = 'files' }" />
    <ConfirmActionModal :show="deviceConfirmation" tone="primary" :title="t('collaboration.ui.device')" :message="t(`collaboration.ui.${deviceHint}`)" :cancel-text="t('common.cancel')" :confirm-text="t(canReconnect ? 'collaboration.ui.actions.reconnect' : 'common.confirm')" :loading="c.busy" @cancel="deviceConfirmation = false" @confirm="async () => { if (canReconnect) await c.claimDriver(); deviceConfirmation = false; c.view.page = 'files' }" />
  </section>
</template>

<style scoped>
.session-actions { display: flex; gap: 12px; padding: 14px 24px; flex-shrink: 0; font-size: 12px; }
.collaboration-panel { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; color: var(--color-text-body); overflow: hidden; }.state-strip { display: flex; align-items: center; gap: 14px; margin: 0 24px; padding: 18px 0; border-bottom: 1px solid #e5eaf0; flex-shrink: 0; }.state-icon { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; background: #edf7f3; color: #278267; flex-shrink: 0; }.warning .state-icon { color: #a66a12; background: #fff7e7; }.state-copy { flex: 1; min-width: 0; }.state-copy strong { display: block; font-size: 14px; font-weight: 600; }.state-copy p { margin: 3px 0 0; font-size: 12px; color: var(--color-text-muted); }.state-copy small { display: block; color: var(--color-text-muted); font-size: 11px; margin-top: 4px; }.state-strip>button { flex-shrink: 0; font-size: 12px; }.error-details { padding: 10px 24px; color: #a66a12; font-size: 12px; max-height: 130px; overflow: auto; flex-shrink: 0; }.error-details summary { cursor: pointer; }.error-details p { margin: 6px 0; overflow-wrap: anywhere; }
.file-filters { display: flex; align-items: center; gap: 4px; padding: 13px 24px; border-bottom: 1px solid #e5eaf0; flex-shrink: 0; }.file-filters button { display: flex; align-items: center; gap: 6px; padding: 5px 10px; border: 0; border-radius: 5px; background: none; color: var(--color-text-muted); font-size: 12px; cursor: pointer; white-space: nowrap; }.file-filters button.active { background: var(--color-primary-50); color: var(--color-primary-600); }.file-filters button:disabled { opacity: .5; cursor: default; }.file-filters small { font-size: 10px; }.scope-label { margin-left: auto; color: var(--color-text-muted); font-size: 11px; white-space: nowrap; }.file-comparison { display: flex; flex: 1; min-height: 0; }.diff-workspace { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; }.diff-note { margin: 0; padding: 12px 16px; color: var(--color-text-muted); font-size: 11px; border-top: 1px solid #e5eaf0; }.empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 24px; color: var(--color-text-muted); text-align: center; }.empty-state strong { margin-top: 15px; font-size: 14px; font-weight: 500; color: var(--color-text-body); }.empty-state p { font-size: 12px; margin-top: 8px; }
.conflict-actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 24px; border-top: 1px solid #e5eaf0; flex-shrink: 0; font-size: 12px; }.conflict-actions>div { display: flex; align-items: center; gap: 10px; }.conflict-actions label { display: flex; align-items: center; gap: 6px; }.conflict-actions input { accent-color: var(--color-primary-600); }.conflict-actions small { color: var(--color-text-muted); font-size: 11px; }.restore-paths { font: 12px/1.8 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }.back-button { align-self: flex-start; padding: 15px 24px; background: none; border: 0; font-size: 12px; color: var(--color-primary-600); cursor: pointer; }.spin { animation: rotate 1.5s linear infinite; }@keyframes rotate { to { transform: rotate(360deg); } }@media(prefers-reduced-motion:reduce) { .spin { animation: none; } }
@media(max-width:720px) { .file-comparison { flex-direction: column; }.state-strip { margin: 0 16px; gap: 10px; }.file-filters { padding: 12px 8px; }.file-filters button { padding: 5px 8px; }.scope-label { display: none; }.conflict-actions { padding: 12px 16px; }.conflict-actions>div { flex-wrap: wrap; gap: 4px; }.state-icon { display: none; }.state-strip>button { padding: 6px 9px; } }
</style>
