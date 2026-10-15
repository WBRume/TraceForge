<script setup lang="ts">
import { computed, proxyRefs, shallowRef, toRaw, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, GitPullRequest, GitBranch, FileText, Clock, Search, Shield } from '@/components/icons'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import CodeComparison from './CodeComparison.vue'
import CollaborationBackups from './CollaborationBackups.vue'
import CollaborationFiles from './CollaborationFiles.vue'
import CollaborationHistory from './CollaborationHistory.vue'
import RepositoryUpdatePanel from './RepositoryUpdatePanel.vue'
import RepositoryUpdateChanges from './RepositoryUpdateChanges.vue'
import RepositoryUpdateEntry from './RepositoryUpdateEntry.vue'
import { useRepositoryUpdates } from '@/composables/collaboration/useRepositoryUpdates'
import { useOpenInIde } from '@/composables/collaboration/useOpenInIde'
import { collaborationFileKey } from '@/composables/collaboration/compare'
import { collaborationReview } from '@/composables/collaboration/review'
import { useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import type { CollaborationBackup, CollaborationConflict } from '@/types/collaboration'

const props = defineProps<{ controller: LocalCollaboration; workspaceId: string; taskId: string }>()
const emit = defineEmits<{ error: [message: string] }>()
const { t } = useI18n()
const c = computed(() => proxyRefs(props.controller))
const updates = useRepositoryUpdates(() => props)
const diffScope = shallowRef<'cumulative' | 'round'>('cumulative')
function showRemoteChanges() {
  c.value.view.page = 'updates'
  const conflict = updates.files.value.find(file => file.conflict)
  if (conflict) updates.selected.value = conflict.key
}
watch(() => props.taskId, () => { diffScope.value = 'cumulative' })
const ide = useOpenInIde(() => c.value, () => props.workspaceId)
watch(() => props.controller, controller => { void controller.loadReview() }, { immediate: true })
watch(ide.error, message => emit('error', message))
const ui = useCollaborationPresentation(() => props.controller)
const downloadOnly = computed(() => c.value.receivedOnce && !c.value.participating)
const tab = computed({ get: () => c.value.view.tab, set: value => { c.value.view.tab = value } })
const pair = computed({ get: () => c.value.view.pair, set: value => { c.value.view.pair = value } })
const selected = computed({ get: () => c.value.view.selected, set: value => { c.value.view.selected = value } })
const checked = computed({ get: () => c.value.view.selectedConflicts, set: value => { c.value.view.selectedConflicts = value } })
const review = computed(() => collaborationReview(c.value, Boolean(ui.value?.localAvailable), diffScope.value))
const files = computed(() => review.value.files.filter(file => diffScope.value === 'cumulative' || tab.value === 'all' || file.kind === tab.value))
function selectDiffScope(scope: 'cumulative' | 'round') {
  tab.value = 'all'
  diffScope.value = scope
}
watch(diffScope, () => { pair.value = 'auto' })
watch(tab, value => { if (value === 'local' || value === 'conflicts') diffScope.value = 'round' }, { immediate: true })

const searchQuery = shallowRef('')
const filteredFiles = computed(() => {
  const list = files.value
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return list
  return list.filter(item => item.path.toLowerCase().includes(query) || (item.repo_slug && item.repo_slug.toLowerCase().includes(query)))
})

const active = computed(() => filteredFiles.value.find(file => file.key === selected.value) || files.value.find(file => file.key === selected.value))
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
  const cumulative = diffScope.value === 'cumulative' && pair.value === 'auto' && file?.kind === 'cloud'
  return { left, right, leftLabel: cumulative ? '远端基线' : t(`collaboration.${leftSource}`), rightLabel: cumulative ? '任务版本' : t(`collaboration.${rightSource}`) }
})
const restoreDescription = computed(() => pendingRestore.value?.conflicts.map(row => {
  const repo = c.value.state?.repositories.find(item => item.task_repository_id === row.task_repository_id)
  return `${repo?.repo_slug || row.task_repository_id}/${row.path}${!row.cloud ? ` · ${t('collaboration.delete')}` : ''}`
}).join('\n') || '')
const canReconnect = computed(() => c.value.canReconnect)
const activeConflict = computed(() => c.value.conflicts.find(item => collaborationFileKey(item.task_repository_id, item.path) === active.value?.key))
const deviceHint = computed(() => c.value.state?.driver_connected === false ? canReconnect.value ? 'reconnectHint' : 'reconnectElsewhereHint' : 'activeDeviceHint')

async function resolveActiveSingle(decision: 'accept' | 'keep') {
  if (!active.value) return
  if (decision === 'accept') {
    const row = c.value.conflicts.find(item => collaborationFileKey(item.task_repository_id, item.path) === active.value?.key)
    if (row && c.value.local?.conflict_set_id) {
      pendingRestore.value = { conflicts: [structuredClone(toRaw(row))], id: c.value.local.conflict_set_id }
    }
  } else {
    const row = c.value.conflicts.find(item => collaborationFileKey(item.task_repository_id, item.path) === active.value?.key)
    if (row && c.value.local?.conflict_set_id) await c.value.restore([structuredClone(toRaw(row))], c.value.local.conflict_set_id, 'keep')
  }
}

watch(filteredFiles, rows => {
  if (!rows.some(row => row.key === selected.value)) {
    selected.value = rows[0]?.key || ''
  }
}, { immediate: true })

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
</script>

<template>
  <section v-if="ui" class="collaboration-panel">
    <!-- 统一二级视图导航栏 -->
    <nav class="drawer-subnav">
      <button class="nav-tab-item" :class="{ active: ['files', 'updates'].includes(c.view.page) }" type="button" @click="c.view.page = 'files'">
        <FileText :size="13" />
        <span>变更差异</span>
      </button>
      <button class="nav-tab-item" :class="{ active: c.view.page === 'settings' }" type="button" @click="c.view.page = 'settings'">
        <GitBranch :size="13" />
        <span>仓库与版本</span>
      </button>
      <button class="nav-tab-item" :class="{ active: c.view.page === 'backups' }" type="button" @click="c.view.page = 'backups'">
        <Clock :size="13" />
        <span>快照备份</span>
      </button>
      <button class="nav-tab-item" :class="{ active: c.view.page === 'history' }" type="button" @click="c.view.page = 'history'">
        <Clock :size="13" />
        <span>协作历史</span>
      </button>
    </nav>

    <ConfirmActionModal :show="c.view.page === 'disconnect'" tone="primary" :title="t('collaboration.session.disconnect')" :message="t('collaboration.session.leaveHint')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.session.disconnect')" :loading="c.busy || c.leaving" @cancel="c.view.page = 'files'" @confirm="async () => { if (await c.leave()) c.view.page = 'files' }" />
    <template v-if="c.view.page === 'settings'">
      <div class="repository-version-settings">
        <RepositoryUpdatePanel :model="updates" :controller="controller" :setup="!c.participating || ui.setup" @device="deviceConfirmation = true" />
      </div>
    </template>
    <template v-else-if="c.view.page === 'backups'">
      <template v-if="backup"><button class="back-button" type="button" @click="backup = null">{{ t('collaboration.ui.backToBackups') }}</button><CodeComparison :path="backup.path" :left-hash="backup.sha256 || undefined" :right-hash="review.local.get(collaborationFileKey(backup.task_repository_id, backup.path))?.sha256" :left-label="t('collaboration.backupSource')" :right-label="t('collaboration.localSource')" :read-text="c.readText" /></template>
      <CollaborationBackups v-else :controller="controller" @select="backup = $event" />
    </template>
    <CollaborationHistory v-else-if="c.view.page === 'history'" :workspace-id="workspaceId" :task-id="taskId" />
    <RepositoryUpdateChanges v-else-if="c.view.page === 'updates'" :model="updates" @back="c.view.page = 'files'" @close="c.view.page = 'files'" @applied="selectDiffScope('cumulative'); c.view.page = 'files'; c.refreshResults()" />
    <template v-else>
      <div class="diff-scope-bar">
        <nav class="diff-purpose-tabs" aria-label="差异用途">
          <button type="button" :class="{ active:diffScope === 'cumulative' }" :aria-pressed="diffScope === 'cumulative'" @click="selectDiffScope('cumulative')">累计差异</button>
          <button type="button" :class="{ active:diffScope === 'round' }" :aria-pressed="diffScope === 'round'" @click="selectDiffScope('round')">本轮差异</button>
        </nav>
        <RepositoryUpdateEntry class="update-entry" :model="updates" @open="showRemoteChanges" />
      </div>
        <!-- 分段筛选条与搜索过滤 -->
        <div class="filter-bar-wrapper">
          <span v-if="diffScope === 'cumulative'" class="result-summary">任务执行成果 <small>{{ review.files.length }} 个文件</small></span>
          <nav v-else class="file-filters" :aria-label="t('collaboration.ui.fileSources')">
            <button v-for="item in filters" :key="item.value" type="button" :class="{ active: tab === item.value, 'is-warning': item.value === 'conflicts' }" :aria-pressed="tab === item.value" :disabled="item.value === 'local' && !ui.localAvailable" :title="item.value === 'local' && !ui.localAvailable ? t('collaboration.ui.localUnavailable') : ''" @click="tab = item.value">
              <span>{{ t(downloadOnly && item.value === 'cloud' ? 'collaboration.session.cloudChanges' : `collaboration.ui.filters.${item.value}`) }}</span>
              <small :class="{ 'warning-badge': item.value === 'conflicts' }">{{ item.count }}</small>
            </button>
          </nav>
          <div class="filter-right-tools">
            <button v-if="diffScope === 'round'" class="human-records-link" type="button" @click="c.view.page = 'history'">人工修改记录</button>
            <div class="file-search-box">
              <Search :size="13" class="search-icon" />
              <input v-model="searchQuery" type="text" placeholder="过滤文件路径..." class="filter-search-input" />
            </div>
          </div>
        </div>

        <!-- 主内容比对区 -->
        <div v-if="filteredFiles.length" class="file-comparison">
          <CollaborationFiles :files="filteredFiles" :repositories="c.state?.repositories || []" :selected="selected" :checked="checked" :can-restore="ui.canRestore" :local-available="ui.localAvailable" :running="ui.running" @select="selected = $event; pair = 'auto'" @check="checkFile" />
          <div v-if="active" class="diff-workspace">
            <CodeComparison :path="`${active.repo_slug}/${active.path}`" :left-hash="comparison.left?.sha256" :right-hash="comparison.right?.sha256" :left-label="comparison.leftLabel" :right-label="comparison.rightLabel" :read-text="c.readText" :open-in-ide="ide.available" :ide-title="ide.hint(active.task_repository_id)" @ide-error="ide.error.value = $event" @open-in-ide="position => ide.open(active!.task_repository_id, active!.path, position.line, position.column)">
              <template v-if="diffScope === 'round'" #tools><BaseSelect v-model="pair" size="sm" :aria-label="t('collaboration.ui.compareVersions')" :options="[{ value: 'auto', label: t('collaboration.ui.defaultComparison') }, { value: 'local-cloud', label: t('collaboration.localCloud'), disabled: !ui.localAvailable }, { value: 'input-cloud', label: t('collaboration.inputCloud') }]" /></template>
            </CodeComparison>
            <div class="diff-note-bar" :class="{ 'is-decision-bar': active.kind === 'conflicts' && ui.canRestore }">
              <p class="diff-note">
                <span class="diff-note-icon">ℹ</span>
                <span>{{ diffScope === 'cumulative' && active.kind === 'cloud' ? '显示任务相对当前远端基线的全部累计修改。' : t(active.kind === 'conflicts' ? ui.running ? 'collaboration.ui.previewConflictHint' : 'collaboration.ui.restoreNotice' : active.kind === 'local' ? 'collaboration.ui.localNotice' : ui.running ? 'collaboration.ui.runningNotice' : 'collaboration.ui.agentNotice') }}</span>
                <span v-if="comparison.left?.mode !== comparison.right?.mode" class="mode-tag"> · {{ t('collaboration.ui.fileMode') }} {{ comparison.left?.mode || '—' }} → {{ comparison.right?.mode || '—' }}</span>
              </p>
              <div v-if="active.kind === 'conflicts' && ui.canRestore" class="single-file-actions">
                <button type="button" class="btn-secondary btn-xs" :disabled="c.busy || activeConflict?.reason === 'PATH_STRUCTURE'" title="保留当前文件，作为下一次发送时的本地修改" @click="resolveActiveSingle('keep')">保留本地</button>
                <button type="button" class="btn-primary btn-xs" :disabled="c.busy" @click="resolveActiveSingle('accept')">采纳 Agent 版本</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 空状态：高品质微光卡片与操作引导 -->
        <div v-else class="empty-state">
          <div class="empty-state-card">
            <div class="empty-state-icon" :class="{ 'is-empty-clean': !review.files.length }">
              <Check v-if="!review.files.length && !downloadOnly" :size="24" />
              <GitPullRequest v-else :size="24" />
            </div>
            <strong>{{ diffScope === 'cumulative' && review.cloudKnown && tab !== 'local' ? '暂无累计修改' : t(!review.cloudKnown && !c.reviewError && tab !== 'local' ? 'collaboration.ui.loadingFiles' : tab === 'local' ? 'collaboration.ui.noLocalChanges' : downloadOnly ? 'collaboration.session.noChanges' : 'collaboration.ui.noAgentChanges') }}</strong>
            <p>{{ diffScope === 'cumulative' && review.cloudKnown && tab !== 'local' ? '任务相对当前远端基线没有文件差异。' : t(tab === 'local' ? 'collaboration.ui.noLocalHint' : downloadOnly ? 'collaboration.session.noChangesHint' : 'collaboration.ui.noAgentHint') }}</p>
            <div v-if="!review.files.length" class="empty-actions">
              <button class="btn-secondary btn-sm" type="button" @click="c.view.page = 'settings'">查看仓库映射</button>
              <button class="btn-secondary btn-sm" type="button" @click="c.view.page = 'backups'">查看历史快照</button>
            </div>
          </div>
        </div>

        <!-- 底部全局操作枢纽 (Action Hub) -->
        <footer v-if="diffScope === 'round' && ui.canRestore && c.conflicts.length" class="conflict-actions">
          <div class="conflict-selection-meta">
            <label class="select-all-label">
              <input type="checkbox" :checked="allChecked" @change="checked = ($event.target as HTMLInputElement).checked ? c.conflicts.map(row => collaborationFileKey(row.task_repository_id, row.path)) : []" />
              <span>{{ t('collaboration.ui.selectAllConflicts') }}</span>
            </label>
            <small class="selection-count-pill">{{ t('collaboration.ui.selectedCount', { count: selectedConflicts.length, total: c.conflicts.length }) }}</small>
            <span class="safety-pill">
              <Shield :size="12" />
              <span>自动快照保护</span>
            </span>
          </div>
          <div class="conflict-buttons">
            <button class="btn-secondary btn-sm" type="button" @click="c.view.page = 'backups'">查看历史备份</button>
            <button class="btn-primary btn-restore-action" type="button" :disabled="!selectedConflicts.length" @click="askRestore">
              {{ t('collaboration.restoreSelected', { count: selectedConflicts.length }) }}
            </button>
          </div>
        </footer>
    </template>
    <ConfirmActionModal :show="Boolean(pendingRestore)" :title="t('collaboration.restoreTitle', { count: pendingRestore?.conflicts.length || 0 })" :message="t('collaboration.backupFirst')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.confirmRestore')" :loading="c.busy" @cancel="pendingRestore = null" @confirm="confirmRestore"><template #content><pre class="restore-paths">{{ restoreDescription }}</pre></template></ConfirmActionModal>
    <ConfirmActionModal :show="deviceConfirmation" tone="primary" :title="t('collaboration.ui.device')" :message="t(`collaboration.ui.${deviceHint}`)" :cancel-text="t('common.cancel')" :confirm-text="t(canReconnect ? 'collaboration.ui.actions.reconnect' : 'common.confirm')" :loading="c.busy" @cancel="deviceConfirmation = false" @confirm="async () => { if (canReconnect) await c.claimDriver(); deviceConfirmation = false; c.view.page = 'files' }" />
  </section>
</template>

<style scoped>
.diff-scope-bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:10px 16px; border-bottom:1px solid #e2e8f0; }
.diff-purpose-tabs { display:flex; gap:2px; padding:3px; border-radius:7px; background:#f1f5f9; }
.diff-purpose-tabs button { border:0; border-radius:5px; padding:5px 12px; color:#64748b; font-size:12px; background:transparent; cursor:pointer; }
.diff-purpose-tabs button.active { color:#0284c7; background:#fff; box-shadow:0 1px 3px #0f172a12; }
.diff-purpose-tabs button:focus-visible { outline:2px solid #38bdf8; outline-offset:2px; }
.update-entry { margin-left:auto; }
.result-summary { font-size:12px; font-weight:500; color:#334155; } .result-summary small { margin-left:8px; color:#64748b; font-size:11px; font-weight:400; }
.human-records-link { border:0; background:none; color:#0284c7; padding:0; font-size:11px; cursor:pointer; }
.repository-version-settings { flex:1; min-height:0; display:flex; overflow:hidden; }
.collaboration-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  color: var(--color-text-body, #334155);
  background: var(--color-surface-white, #ffffff);
  overflow: hidden;
}

/* 统一二级视图导航栏 */
.drawer-subnav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: 6px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.nav-tab-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}
.nav-tab-item:hover {
  color: #0f172a;
  background: #f1f5f9;
}
.nav-tab-item.active {
  color: #0284c7;
  background: #ffffff;
  border-color: #e2e8f0;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
  font-weight: 600;
}

/* 筛选与搜索工具条 */
.filter-bar-wrapper {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 18px;
  gap: 12px;
  flex-shrink: 0;
  border-bottom: 1px solid #e2e8f0;
}
.file-filters {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.file-filters button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.file-filters button:hover { color: #0f172a; }
.file-filters button.active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.file-filters button:disabled { opacity: .45; cursor: default; }
.file-filters small {
  font-size: 10px;
  font-weight: 600;
  padding: 0 5px;
  border-radius: 10px;
  background: rgba(148, 163, 184, 0.2);
  color: #64748b;
}
.file-filters button.active small {
  background: #f0f9ff;
  color: #0284c7;
}
.file-filters small.warning-badge {
  background: #f59e0b;
  color: #ffffff;
}

.filter-right-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}
.file-search-box {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 3px 8px;
  transition: all 0.15s ease;
}
.file-search-box:focus-within {
  background: #ffffff;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}
.search-icon { color: #94a3b8; flex-shrink: 0; }
.filter-search-input {
  border: 0;
  background: transparent;
  font-size: 11.5px;
  color: #0f172a;
  outline: none;
  width: 140px;
}
.filter-search-input::placeholder { color: #94a3b8; }
.scope-label {
  color: #64748b;
  font-size: 11px;
  white-space: nowrap;
}

/* 主内容对比区 */
.file-comparison { display: flex; flex: 1; min-height: 0; min-width: 0; background: #ffffff; }
.diff-workspace { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; background: #ffffff; }
.diff-note-bar {
  padding: 8px 16px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.diff-note {
  margin: 0;
  color: #64748b;
  font-size: 11.5px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.diff-note-icon {
  display: inline-grid;
  place-items: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #e2e8f0;
  font-size: 10px;
  font-weight: bold;
}
.mode-tag { font-family: var(--font-mono, monospace); font-size: 10.5px; }

.single-file-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.btn-xs {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.15s ease;
}
.btn-secondary.btn-xs {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
}
.btn-secondary.btn-xs:hover { background: #f8fafc; color: #0f172a; }
.btn-primary.btn-xs {
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  color: #ffffff;
  border: 0;
  box-shadow: 0 1px 3px rgba(2, 132, 199, 0.2);
}
.btn-primary.btn-xs:hover {
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
}

/* 空状态卡片 */
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 36px 24px;
  background: #f8fafc;
}
.empty-state-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 32px 40px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
  max-width: 420px;
}
.empty-state-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: #f1f5f9;
  color: #64748b;
  display: grid;
  place-items: center;
  margin-bottom: 12px;
}
.empty-state-icon.is-empty-clean {
  background: #ecfdf5;
  color: #059669;
}
.empty-state-card strong { font-size: 14px; font-weight: 600; color: #0f172a; }
.empty-state-card p { font-size: 12px; color: #64748b; margin-top: 6px; line-height: 1.5; }
.empty-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
}
.btn-sm {
  font-size: 11.5px;
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-sm:hover {
  background: #f8fafc;
  color: #0f172a;
}

/* 底部全局决策枢纽 */
.conflict-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
  flex-shrink: 0;
  box-shadow: 0 -2px 10px rgba(15, 23, 42, 0.03);
}
.conflict-selection-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.select-all-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #0f172a;
  cursor: pointer;
}
.select-all-label input { accent-color: #0284c7; cursor: pointer; }
.selection-count-pill {
  color: #64748b;
  font-size: 11.5px;
}
.safety-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #d1fae5;
  padding: 1px 7px;
  border-radius: 4px;
}
.conflict-buttons {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-restore-action {
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  box-shadow: 0 2px 6px rgba(2, 132, 199, 0.25);
  font-weight: 600;
  font-size: 12px;
  padding: 6px 16px;
  border-radius: 6px;
  color: #ffffff;
  border: 0;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-restore-action:hover:not(:disabled) {
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
  box-shadow: 0 4px 12px rgba(2, 132, 199, 0.35);
  transform: translateY(-1px);
}
.btn-restore-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.restore-paths { font: 12px/1.8 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.back-button { align-self: flex-start; padding: 14px 20px; background: none; border: 0; font-size: 12px; font-weight: 500; color: #0284c7; cursor: pointer; }

@media(max-width:720px) {
  .file-comparison { flex-direction: column; }
  .filter-bar-wrapper { padding: 4px 14px 10px; flex-wrap: wrap; }
  .filter-right-tools { width: 100%; justify-content: space-between; }
  .scope-label { display: none; }
  .conflict-actions { padding: 12px 14px; flex-wrap: wrap; }
  .conflict-selection-meta { flex-wrap: wrap; gap: 6px; }
}
</style>
