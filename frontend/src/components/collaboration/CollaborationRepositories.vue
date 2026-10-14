<script setup lang="ts">
import { computed, proxyRefs, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { GitBranch, GitCommitHorizontal, FolderGit2, FolderOpen, Monitor, ArrowRight, Check, ChevronDown, AlertCircle } from '@/components/icons'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import type { UpdateSummary, UpdateRepository } from '@/services/repositoryUpdates'

const props = defineProps<{
  controller?: LocalCollaboration
  setup: boolean
  embedded?: boolean
  versions?: UpdateSummary['repositories']
  targets?: UpdateRepository[]
}>()
const emit = defineEmits<{ device: [] }>()
const { t } = useI18n()
const c = computed(() => props.controller ? proxyRefs(props.controller) : null)
const repos = computed(() => {
  const localRepos = c.value?.state?.repositories || []
  const versions = props.versions?.length ? props.versions : localRepos.map(repo => ({
    id: repo.task_repository_id, name: repo.repo_slug, branch: repo.branch_name,
    baseline: repo.base_commit_sha, creation_baseline: repo.base_commit_sha,
  }))
  return versions.map(repo => ({ ...repo,
    path: (!props.setup && c.value?.local?.repositories?.find(row => row.task_repository_id === repo.id)?.local_worktree_path)
      || c.value?.mappings[repo.id]?.local_path || '',
    check: c.value?.mappingChecks.find(row => row.task_repository_id === repo.id),
    target: props.targets?.find(row => row.id === repo.id)?.target,
  }))
})
const allMapped = computed(() => repos.value.length > 0 && repos.value.every(repo => repo.path))
const resumable = computed(() => Boolean(c.value?.local?.baseline && (!c.value.local.released || c.value.local.suspended)))
const canPrepare = computed(() => c.value?.available && (!c.value.participating || c.value.preparationRequired))
const problemText = (code: string) => t(code === 'HEAD_MISMATCH' ? 'collaboration.headMismatch' : code === 'WORKTREE_DIRTY' ? 'collaboration.worktreeDirty' : 'collaboration.ui.repoCheckError', { code })
watch(() => props.setup && allMapped.value && canPrepare.value && !c.value?.loading, ready => {
  if (ready && c.value && !c.value.busy && !c.value.mappingChecks.length) void c.value.checkMappings()
}, { immediate: true })
</script>

<template>
  <section class="repository-settings" :class="{ embedded }">
    <header v-if="!embedded" class="settings-heading">
      <div class="settings-heading-main">
        <h2>任务仓库</h2>
        <span>版本基线与本地目录映射</span>
      </div>
    </header>
    <div class="repositories">
      <article v-for="repo in repos" :key="repo.id" class="repository-row" :data-repository-id="repo.id">
        <header class="repo-heading">
          <span class="repository-icon"><FolderGit2 :size="18" /></span>
          <div class="repo-title-wrap">
            <strong class="repo-name">{{ repo.name }}</strong>
            <span class="branch-pill" :title="repo.branch">
              <GitBranch :size="11" />
              <code>{{ repo.branch }}</code>
            </span>
          </div>
          <span v-if="repo.target" class="version-state" :class="{ updated: repo.target !== repo.baseline }">
            <span class="state-dot" />
            <span>{{ repo.target === repo.baseline ? '已是远端版本' : '有远端更新' }}</span>
          </span>
        </header>

        <div class="repo-context">
          <!-- Git 提交节点流转看板 -->
          <div class="version-track">
            <span class="context-label"><GitCommitHorizontal :size="14" />版本提交</span>
            <div class="commit-flow">
              <div class="commit-node" title="当前云端任务基准提交">
                <span class="node-tag">基线 (Base)</span>
                <code class="commit-token" :title="repo.baseline">{{ repo.baseline.slice(0, 8) }}</code>
              </div>
              <template v-if="repo.target && repo.target !== repo.baseline">
                <div class="version-connector">
                  <span class="flow-line" />
                  <ArrowRight :size="13" class="flow-arrow" />
                </div>
                <div class="commit-node target-node" title="远端分支最新提交">
                  <span class="node-tag">远端 (Target)</span>
                  <code class="commit-token target-token" :title="repo.target">{{ repo.target.slice(0, 8) }}</code>
                </div>
              </template>
            </div>
          </div>

          <!-- 本地目录映射控制区 -->
          <div class="mapping-row">
            <span class="context-label"><Monitor :size="14" />本地映射</span>
            <div class="path-control" :class="{ empty: !repo.path }">
              <span :title="repo.path" class="path-text">{{ repo.path || (c?.available ? '尚未关联本地仓库' : '在桌面端关联本地仓库') }}</span>
              <button v-if="canPrepare" class="path-action" type="button" :disabled="c?.busy" :aria-label="`${repo.path ? '更换' : '选择'} ${repo.name} 本地仓库`" @click="c?.selectMapping(repo.id)">
                <FolderOpen :size="13" />
                <span>{{ repo.path ? '更换' : '选择目录' }}</span>
              </button>
              <button v-else-if="c?.participating && c.driver && repo.path" class="path-action" type="button" @click="c.openDirectory(repo.id)">
                <FolderOpen :size="13" />
                <span>打开</span>
              </button>
            </div>
          </div>

          <div v-if="setup && repo.path" class="local-state" :class="{ warning: repo.check?.errors.length }">
            <AlertCircle v-if="repo.check?.errors.length" :size="13" />
            <Check v-else-if="repo.check" :size="13" />
            <span v-else class="state-dot" />
            <span>{{ t(repo.check?.errors.length ? 'collaboration.ui.checkFailed' : resumable ? 'collaboration.session.resumeBaseline' : repo.check ? 'collaboration.ui.checkPassed' : 'collaboration.ui.notChecked') }}</span>
          </div>

          <details class="check-details">
            <summary><ChevronDown :size="12" />版本详情</summary>
            <dl>
              <dt>云端基线</dt><dd>{{ repo.baseline }}</dd>
              <template v-if="repo.creation_baseline !== repo.baseline"><dt>任务创建时</dt><dd>{{ repo.creation_baseline }}</dd></template>
              <template v-if="repo.check"><dt>本地 HEAD</dt><dd>{{ repo.check.local_head }} · {{ repo.check.local_branch }}</dd></template>
            </dl>
            <pre v-if="setup && repo.check?.changes.length">{{ repo.check.changes.join('\n') }}</pre>
          </details>

          <p v-for="problem in setup ? repo.check?.errors || [] : []" :key="problem" class="repo-error" role="alert">
            <AlertCircle :size="13" />{{ problemText(problem) }}
          </p>
        </div>
      </article>
    </div>
    <div v-if="c && !setup" class="device-setting">
      <Monitor :size="15" />
      <span>{{ t('collaboration.ui.device') }}<small>{{ t(c.state?.driver_connected === false ? 'collaboration.ui.deviceOffline' : c.driver ? 'collaboration.ui.thisDevice' : 'collaboration.ui.otherDevice') }}</small></span>
      <button v-if="c.available && !c.driver" class="text-action" type="button" @click="emit('device')">{{ t('collaboration.ui.deviceDetails') }}</button>
    </div>
  </section>
</template>

<style scoped>
.repository-settings {
  --repo-border: var(--color-border-light, #e2e8f0);
  --repo-bg: var(--color-surface-white, #ffffff);
  color: var(--color-text-body, #334155);
  padding: 0 20px;
  overflow: auto;
  flex: 1;
  min-height: 0;
}
.repository-settings.embedded {
  overflow: visible;
  flex: initial;
  padding: 0;
}
.settings-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 0 10px;
  border-bottom: 1px solid var(--repo-border);
}
.settings-heading-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.settings-heading h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-title, #0f172a);
}
.settings-heading span {
  color: var(--color-text-muted, #64748b);
  font-size: 11px;
}
.repositories {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 0;
}
.repository-row {
  padding: 16px;
  border: 1px solid var(--repo-border);
  border-radius: 12px;
  background: var(--repo-bg);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.repository-row:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
}
.repo-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.repository-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid #e0f2fe;
  color: #0284c7;
  background: #f0f9ff;
  border-radius: 9px;
  flex-shrink: 0;
}
.repo-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.repo-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-title, #0f172a);
  overflow-wrap: anywhere;
}
.branch-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 2px 7px;
  border-radius: 5px;
  color: #475569;
  font-size: 11px;
}
.branch-pill code {
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-mono, "JetBrains Mono", Menlo, monospace);
  white-space: nowrap;
}
.version-state {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 9999px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #16a34a;
  flex-shrink: 0;
}
.version-state.updated {
  background: #fffbeb;
  border-color: #fde68a;
  color: #d97706;
}
.state-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  display: inline-block;
  flex-shrink: 0;
}
.repo-context {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.version-track, .mapping-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.context-label {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  width: 76px;
  color: var(--color-text-muted, #64748b);
  font-size: 11px;
}
.commit-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.commit-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.commit-node.target-node {
  background: #f0f9ff;
  border-color: #bae6fd;
}
.node-tag {
  font-size: 10px;
  color: #94a3b8;
}
.target-node .node-tag {
  color: #0284c7;
}
.commit-token {
  font-family: var(--font-mono, "JetBrains Mono", Menlo, monospace);
  font-size: 11px;
  font-weight: 500;
  color: #334155;
}
.target-token {
  color: #0369a1;
  font-weight: 600;
}
.version-connector {
  display: flex;
  align-items: center;
  color: #94a3b8;
}
.flow-line {
  width: 14px;
  height: 1px;
  background: #cbd5e1;
}
.flow-arrow {
  margin-left: -2px;
  color: #0284c7;
}
.path-control {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
  padding: 6px 10px;
  background: #f8fafc;
  border: 1px solid var(--repo-border);
  border-radius: 7px;
  transition: border-color 0.15s, background-color 0.15s;
}
.path-control:focus-within, .path-control:hover {
  border-color: #93c5fd;
  background: #ffffff;
}
.path-control.empty {
  border-style: dashed;
  background: transparent;
}
.path-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono, "JetBrains Mono", Menlo, monospace);
  font-size: 11px;
  line-height: 1.6;
  color: #334155;
}
.empty .path-text {
  font-family: inherit;
  color: var(--color-text-muted, #94a3b8);
}
.path-action, .text-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #0284c7;
  border-radius: 5px;
  font-family: inherit;
  font-weight: 500;
  font-size: 11px;
  cursor: pointer;
  padding: 3px 8px;
  white-space: nowrap;
  transition: background-color 0.15s, border-color 0.15s;
}
.path-action:hover:not(:disabled), .text-action:hover:not(:disabled) {
  background: #dbeafe;
  border-color: #bfdbfe;
}
.path-action:disabled {
  opacity: 0.45;
  cursor: default;
}
.path-action:focus-visible, .text-action:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}
.local-state {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 2px 0 0 88px;
  font-size: 11px;
  color: #16a34a;
}
.local-state.warning {
  color: #d97706;
}
.check-details {
  margin-top: 4px;
  color: var(--color-text-muted, #64748b);
  font-size: 11px;
}
.check-details summary {
  display: flex;
  align-items: center;
  gap: 4px;
  width: fit-content;
  cursor: pointer;
  list-style: none;
  font-size: 10px;
  color: #64748b;
}
.check-details summary::-webkit-details-marker {
  display: none;
}
.check-details summary svg {
  transition: transform 0.15s;
  transform: rotate(-90deg);
}
.check-details[open] summary svg {
  transform: rotate(0);
}
.check-details dl {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 6px 12px;
  margin: 8px 0;
}
.check-details dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-family: var(--font-mono, monospace);
}
.check-details pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 120px;
  overflow: auto;
}
.repo-error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 11px;
  line-height: 1.6;
  color: #b45309;
  margin: 4px 0 0;
}
.repo-error svg {
  flex-shrink: 0;
  margin-top: 3px;
}
.device-setting {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 0;
  font-size: 12px;
  border-top: 1px solid var(--repo-border);
}
.device-setting > span {
  flex: 1;
}
.device-setting small {
  display: block;
  margin-top: 3px;
  color: var(--color-text-muted, #64748b);
}
@container (max-width: 560px) {
  .repository-settings {
    padding: 0 14px;
  }
  .repo-heading {
    flex-wrap: wrap;
    gap: 8px;
  }
  .context-label {
    width: 68px;
  }
  .local-state {
    margin-left: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  * {
    transition: none !important;
  }
}
</style>
