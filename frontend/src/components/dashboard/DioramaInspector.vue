<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileCode,
  Folder,
  GitBranch,
  GitCommitHorizontal,
  MessageSquare,
  Pin,
  Target,
  Users,
  X,
} from '@/components/icons'
import { isActiveTaskStatus, taskDisplayStatus, taskStatusKey } from '@/utils/taskStatus'
import type {
  DioramaHit,
  DioramaMemberItem,
  DioramaModuleHeatStats,
  DioramaModuleItem,
  DioramaRepoItem,
  DioramaTaskItem,
  DioramaTimelineDay,
} from '@/types/dashboardDiorama'

const props = defineProps<{
  workspaceId: string
  repos: DioramaRepoItem[]
  members: DioramaMemberItem[]
  tasks: DioramaTaskItem[]
  timeline: DioramaTimelineDay[]
  moduleHeatMap: Map<string, DioramaModuleHeatStats>
  selectedHit: DioramaHit | null
  pinnedTaskId: string | null
  hoveredTaskId: string | null
  activeMemberId: string | null
  collapsed: boolean
}>()

const emit = defineEmits<{
  'toggle-collapse': []
  'toggle-member': [memberId: string]
  'toggle-pin-task': [taskId: string]
  'hover-task': [taskId: string | null]
  'focus-entity': [kind: 'repo' | 'module', id: string]
  'select-module': [repo: DioramaRepoItem, mod: DioramaModuleItem]
  'clear-focus': []
}>()

const { t } = useI18n()
const router = useRouter()

const activeTab = shallowRef<'collab' | 'detail'>('collab')

watch(() => props.selectedHit, (hit) => {
  if (hit) activeTab.value = 'detail'
})

const memberTaskCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const task of props.tasks) {
    counts.set(task.creator_id, (counts.get(task.creator_id) ?? 0) + 1)
  }
  return counts
})

const selectedModule = computed(() => (props.selectedHit?.kind === 'module' ? props.selectedHit.module ?? null : null))
const selectedRepo = computed(() => props.selectedHit?.repo ?? null)

const selectedModuleHeat = computed<DioramaModuleHeatStats>(() => {
  const mod = selectedModule.value
  if (!mod) return { commits: 0, added: 0, deleted: 0, score: 0 }
  return props.moduleHeatMap.get(mod.id) ?? {
    commits: mod.commits,
    added: mod.added,
    deleted: mod.deleted,
    score: 0,
  }
})

const selectedRepoWindowStats = computed(() => {
  const repo = selectedRepo.value
  if (!repo) return { commits: 0, added: 0, deleted: 0 }
  let commits = 0
  let added = 0
  let deleted = 0
  for (const mod of repo.modules) {
    const st = props.moduleHeatMap.get(mod.id)
    if (st) {
      commits += st.commits
      added += st.added
      deleted += st.deleted
    }
  }
  return { commits, added, deleted }
})

const selectedModuleSparkline = computed(() => {
  const mod = selectedModule.value
  if (!mod || !props.timeline.length) return []
  const raw = props.timeline.map(day => ({
    date: day.date,
    commits: day.module_heat?.[mod.id]?.commits ?? 0,
  }))
  const maxVal = Math.max(1, ...raw.map(item => item.commits))
  return raw.map(item => ({
    ...item,
    heightPct: item.commits > 0 ? Math.max(18, Math.round((item.commits / maxVal) * 100)) : 8,
  }))
})

const relatedTasks = computed(() => {
  const hit = props.selectedHit
  if (!hit) return []
  if (hit.kind === 'module' && hit.module) {
    const mid = hit.module.id
    return props.tasks.filter(task => task.modules.includes(mid))
  }
  return props.tasks.filter(task => task.repos.includes(hit.repo.id))
})

const sortedRepoModules = computed(() => {
  const repo = selectedRepo.value
  if (!repo) return []
  return repo.modules
    .slice()
    .sort((a, b) => {
      const sa = props.moduleHeatMap.get(a.id)?.score ?? 0
      const sb = props.moduleHeatMap.get(b.id)?.score ?? 0
      return (sb - sa) || (b.loc - a.loc)
    })
    .slice(0, 14)
})

function statusClass(task: DioramaTaskItem): string {
  const st = taskDisplayStatus(task.status, task.interrupt_kind)
  if (st === 'RUNNING' || st === 'AWAITING_INPUT') return 'is-running'
  if (st === 'COMPLETED') return 'is-completed'
  if (st === 'FAILED' || st === 'ABNORMAL_INTERRUPTED') return 'is-failed'
  return 'is-neutral'
}

function formatLoc(loc: number): string {
  return loc >= 1000 ? `${(loc / 1000).toFixed(1)}k` : String(loc)
}

function openTaskChat(taskId: string) {
  router.push({ name: 'taskChat', params: { wsId: props.workspaceId, taskId } })
}

function openTaskDetail(taskId: string) {
  router.push({ name: 'workspaceAssetTaskDetail', params: { wsId: props.workspaceId, taskId } })
}

function openRequirement(reqId: string) {
  router.push({
    name: 'workspaceAssetsRequirementDetail',
    params: { wsId: props.workspaceId, requirementId: reqId },
  })
}
</script>

<template>
  <aside class="diorama-inspector" :class="{ 'is-collapsed': collapsed }">
    <button
      type="button"
      class="collapse-handle"
      :title="collapsed ? t('dashboard.diorama.expand_inspector') : t('dashboard.diorama.collapse_inspector')"
      @click="emit('toggle-collapse')"
    >
      <ChevronLeft v-if="collapsed" class="handle-icon" />
      <ChevronRight v-else class="handle-icon" />
    </button>

    <template v-if="!collapsed">
      <div class="inspector-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          class="inspector-tab"
          :class="{ 'is-active': activeTab === 'collab' }"
          :aria-selected="activeTab === 'collab'"
          @click="activeTab = 'collab'"
        >
          <Users class="tab-icon" />
          <span>{{ t('dashboard.diorama.tab_collab') }}</span>
          <span class="tab-count">{{ tasks.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="inspector-tab"
          :class="{ 'is-active': activeTab === 'detail' }"
          :aria-selected="activeTab === 'detail'"
          @click="activeTab = 'detail'"
        >
          <Folder class="tab-icon" />
          <span>{{ t('dashboard.diorama.tab_detail') }}</span>
        </button>
      </div>

      <div class="inspector-body">
        <!-- Tab 1: Members & Tasks Collaboration Focus -->
        <template v-if="activeTab === 'collab'">
          <section class="panel-section">
            <div class="section-head">
              <h4 class="section-title">{{ t('dashboard.diorama.members_title') }}</h4>
              <button
                v-if="activeMemberId || pinnedTaskId"
                type="button"
                class="clear-link"
                @click="emit('clear-focus')"
              >
                <X class="mini-icon" />
                {{ t('dashboard.diorama.clear_focus') }}
              </button>
            </div>

            <div v-if="members.length" class="member-chips">
              <button
                v-for="member in members"
                :key="member.id"
                type="button"
                class="member-chip"
                :class="{ 'is-active': activeMemberId === member.id }"
                @click="emit('toggle-member', member.id)"
              >
                <UserAvatar
                  :display-name="member.display_name"
                  :email="member.email"
                  :user-id="member.id"
                  :avatar-url="member.avatar_url"
                  :avatar-svg="member.avatar_svg"
                  :accent-color="member.color"
                  size="xs"
                />
                <span class="member-name">{{ member.display_name }}</span>
                <span v-if="memberTaskCounts.get(member.id)" class="member-badge">
                  {{ memberTaskCounts.get(member.id) }}
                </span>
              </button>
            </div>
            <div v-else class="empty-hint">{{ t('dashboard.diorama.no_members') }}</div>
          </section>

          <section class="panel-section">
            <div class="section-head">
              <h4 class="section-title">{{ t('dashboard.diorama.tasks_title') }}</h4>
              <span class="section-hint">{{ t('dashboard.diorama.tasks_hint') }}</span>
            </div>

            <div v-if="tasks.length" class="task-list">
              <div
                v-for="task in tasks"
                :key="task.id"
                class="task-card"
                :class="{
                  'is-pinned': pinnedTaskId === task.id,
                  'is-hovered': hoveredTaskId === task.id,
                }"
                @mouseenter="emit('hover-task', task.id)"
                @mouseleave="emit('hover-task', null)"
                @click="emit('toggle-pin-task', task.id)"
              >
                <div class="task-card-top">
                  <span class="task-status-dot" :class="{ 'is-live': isActiveTaskStatus(task.status) }" />
                  <span class="task-name" :title="task.name">{{ task.name }}</span>
                  <span v-if="pinnedTaskId === task.id" class="pin-indicator" :title="t('dashboard.diorama.pinned')">
                    <Pin class="mini-icon" />
                  </span>
                </div>

                <div class="task-meta-row">
                  <span class="status-pill" :class="statusClass(task)">
                    {{ t(taskStatusKey(taskDisplayStatus(task.status, task.interrupt_kind))) }}
                  </span>
                  <span v-if="task.creator_name" class="task-author">{{ task.creator_name }}</span>
                  <span class="task-scope">
                    {{ t('dashboard.diorama.task_scope', { repos: task.repos.length, modules: task.modules.length }) }}
                  </span>
                </div>

                <div v-if="task.requirement_titles.length" class="req-tags">
                  <button
                    v-for="(title, idx) in task.requirement_titles.slice(0, 2)"
                    :key="task.requirement_ids[idx] || title"
                    type="button"
                    class="req-tag"
                    @click.stop="task.requirement_ids[idx] && openRequirement(task.requirement_ids[idx])"
                  >
                    {{ title }}
                  </button>
                </div>

                <div class="task-card-foot">
                  <span class="churn-nums">
                    <span class="num-add">+{{ task.added }}</span>
                    <span class="num-del">-{{ task.deleted }}</span>
                  </span>
                  <div class="task-actions">
                    <button
                      type="button"
                      class="card-action-btn"
                      :title="t('dashboard.diorama.open_task_chat')"
                      @click.stop="openTaskChat(task.id)"
                    >
                      <MessageSquare class="mini-icon" />
                      <span>{{ t('dashboard.diorama.open_chat_short') }}</span>
                    </button>
                    <button
                      type="button"
                      class="card-action-btn"
                      :title="t('dashboard.diorama.open_task_detail')"
                      @click.stop="openTaskDetail(task.id)"
                    >
                      <ExternalLink class="mini-icon" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-else :image-size="56" :description="t('dashboard.diorama.no_tasks')" />
          </section>
        </template>

        <!-- Tab 2: Selected Building / Repo Plinth Detail -->
        <template v-else>
          <template v-if="selectedHit && selectedModule && selectedRepo">
            <section class="panel-section">
              <div class="entity-header">
                <div class="entity-title-wrap">
                  <div class="entity-repo-line">
                    <span class="repo-dot" :style="{ backgroundColor: selectedRepo.color }" />
                    <span class="entity-repo-name">{{ selectedRepo.name }}</span>
                    <span class="entity-branch">
                      <GitBranch class="mini-icon" />
                      {{ selectedRepo.branch }}
                    </span>
                  </div>
                  <h3 class="entity-name">{{ selectedModule.name }}</h3>
                </div>
                <el-button
                  size="small"
                  @click="emit('focus-entity', 'module', selectedModule.id)"
                >
                  <Target class="mini-icon" />
                  <span>{{ t('dashboard.diorama.focus_camera') }}</span>
                </el-button>
              </div>

              <div class="metric-grid">
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_loc') }}</span>
                  <strong class="metric-val">{{ formatLoc(selectedModule.loc) }}</strong>
                </div>
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_files') }}</span>
                  <strong class="metric-val">{{ selectedModule.file_count }}</strong>
                </div>
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_commits') }}</span>
                  <strong class="metric-val is-primary">{{ selectedModuleHeat.commits }}</strong>
                </div>
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_churn') }}</span>
                  <strong class="metric-val churn-nums">
                    <span class="num-add">+{{ selectedModuleHeat.added }}</span>
                    <span class="num-del">-{{ selectedModuleHeat.deleted }}</span>
                  </strong>
                </div>
              </div>
            </section>

            <section v-if="selectedModuleSparkline.length" class="panel-section">
              <div class="section-head">
                <h4 class="section-title">{{ t('dashboard.diorama.activity_trend') }}</h4>
              </div>
              <div class="mini-sparkline">
                <div
                  v-for="bar in selectedModuleSparkline"
                  :key="bar.date"
                  class="mini-spark-col"
                  :title="`${bar.date} · ${bar.commits}`"
                >
                  <span
                    class="mini-spark-bar"
                    :class="{ 'has-data': bar.commits > 0 }"
                    :style="{ height: `${bar.heightPct}%` }"
                  />
                </div>
              </div>
            </section>

            <section v-if="relatedTasks.length" class="panel-section">
              <div class="section-head">
                <h4 class="section-title">{{ t('dashboard.diorama.related_tasks') }}</h4>
                <span class="tab-count">{{ relatedTasks.length }}</span>
              </div>
              <div class="compact-list">
                <div
                  v-for="task in relatedTasks.slice(0, 6)"
                  :key="task.id"
                  class="compact-row is-clickable"
                  @click="emit('toggle-pin-task', task.id)"
                >
                  <span class="compact-main" :title="task.name">{{ task.name }}</span>
                  <button
                    type="button"
                    class="card-action-btn"
                    :title="t('dashboard.diorama.open_task_chat')"
                    @click.stop="openTaskChat(task.id)"
                  >
                    <MessageSquare class="mini-icon" />
                  </button>
                </div>
              </div>
            </section>

            <section class="panel-section">
              <div class="section-head">
                <h4 class="section-title">{{ t('dashboard.diorama.files_title') }}</h4>
                <span class="tab-count">{{ selectedModule.files.length }}</span>
              </div>
              <div v-if="selectedModule.files.length" class="compact-list">
                <div v-for="file in selectedModule.files.slice(0, 14)" :key="file.path" class="file-row">
                  <FileCode class="file-icon" />
                  <div class="file-info">
                    <span class="file-name" :title="file.path">{{ file.name }}</span>
                    <span class="file-sub">{{ file.path }}</span>
                  </div>
                  <div class="file-stats">
                    <span class="mono-dim">{{ formatLoc(file.loc) }}</span>
                    <span v-if="file.commits" class="commit-pill">{{ file.commits }}c</span>
                  </div>
                </div>
              </div>
              <div v-else class="empty-hint">{{ t('dashboard.diorama.no_files') }}</div>
            </section>

            <section class="panel-section">
              <div class="section-head">
                <h4 class="section-title">{{ t('dashboard.diorama.recent_commits') }}</h4>
              </div>
              <div v-if="selectedModule.recent_commits.length" class="commit-list">
                <div
                  v-for="commit in selectedModule.recent_commits.slice(0, 8)"
                  :key="`${commit.hash}:${commit.date}`"
                  class="commit-row"
                >
                  <div class="commit-top">
                    <GitCommitHorizontal class="commit-icon" />
                    <code class="commit-hash">{{ commit.hash }}</code>
                    <span class="commit-date">{{ commit.date }}</span>
                    <span class="churn-nums commit-churn">
                      <span class="num-add">+{{ commit.added }}</span>
                      <span class="num-del">-{{ commit.deleted }}</span>
                    </span>
                  </div>
                  <p class="commit-subject" :title="commit.subject">{{ commit.subject }}</p>
                </div>
              </div>
              <div v-else class="empty-hint">{{ t('dashboard.diorama.no_commits_module') }}</div>
            </section>
          </template>

          <template v-else-if="selectedHit && selectedRepo">
            <section class="panel-section">
              <div class="entity-header">
                <div class="entity-title-wrap">
                  <div class="entity-repo-line">
                    <span class="repo-dot" :style="{ backgroundColor: selectedRepo.color }" />
                    <span class="entity-branch">
                      <GitBranch class="mini-icon" />
                      {{ selectedRepo.branch }}
                    </span>
                  </div>
                  <h3 class="entity-name">{{ selectedRepo.name }}</h3>
                </div>
                <el-button size="small" @click="emit('focus-entity', 'repo', selectedRepo.id)">
                  <Target class="mini-icon" />
                  <span>{{ t('dashboard.diorama.focus_camera') }}</span>
                </el-button>
              </div>

              <div class="metric-grid">
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_loc') }}</span>
                  <strong class="metric-val">{{ formatLoc(selectedRepo.loc) }}</strong>
                </div>
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_files') }}</span>
                  <strong class="metric-val">{{ selectedRepo.file_count }}</strong>
                </div>
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_modules') }}</span>
                  <strong class="metric-val">{{ selectedRepo.module_count }}</strong>
                </div>
                <div class="metric-cell">
                  <span class="metric-label">{{ t('dashboard.diorama.stat_commits') }}</span>
                  <strong class="metric-val is-primary">{{ selectedRepoWindowStats.commits }}</strong>
                </div>
              </div>
            </section>

            <section class="panel-section">
              <div class="section-head">
                <h4 class="section-title">{{ t('dashboard.diorama.repo_modules_title') }}</h4>
                <span class="tab-count">{{ selectedRepo.modules.length }}</span>
              </div>
              <div v-if="sortedRepoModules.length" class="compact-list">
                <button
                  v-for="mod in sortedRepoModules"
                  :key="mod.id"
                  type="button"
                  class="compact-row is-clickable"
                  @click="emit('select-module', selectedRepo, mod)"
                >
                  <span class="compact-main">{{ mod.name }}</span>
                  <span class="file-stats">
                    <span class="mono-dim">{{ formatLoc(mod.loc) }}</span>
                    <span v-if="moduleHeatMap.get(mod.id)?.commits" class="commit-pill">
                      {{ moduleHeatMap.get(mod.id)?.commits }}c
                    </span>
                  </span>
                </button>
              </div>
              <div v-else class="empty-hint">{{ t('dashboard.diorama.repo_no_modules') }}</div>
            </section>
          </template>

          <div v-else class="detail-empty">
            <el-empty :image-size="60" :description="t('dashboard.diorama.select_prompt')" />
          </div>
        </template>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.diorama-inspector {
  position: relative;
  width: 332px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-white);
  border-left: 1px solid #e2e8f0;
  transition: width var(--transition-base);
}

.diorama-inspector.is-collapsed {
  width: 34px;
}

.collapse-handle {
  position: absolute;
  left: -13px;
  top: 14px;
  z-index: 15;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  border: 1px solid #e2e8f0;
  background: var(--color-surface-white);
  color: #64748b;
  box-shadow: var(--shadow-sm);
  transition: all var(--transition-fast);
}

.collapse-handle:hover {
  border-color: var(--color-primary-500);
  color: var(--color-primary-600);
}

.diorama-inspector.is-collapsed .collapse-handle {
  left: 4px;
}

.handle-icon {
  width: 14px;
  height: 14px;
}

.inspector-tabs {
  display: flex;
  padding: 8px 12px 0;
  gap: 6px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.inspector-tab {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: #64748b;
  font-size: 12.5px;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.inspector-tab:hover {
  color: var(--color-text-title);
}

.inspector-tab.is-active {
  color: var(--color-primary-700);
  font-weight: 600;
  border-bottom-color: var(--color-primary-500);
}

.tab-icon {
  width: 14px;
  height: 14px;
}

.tab-count {
  padding: 0 6px;
  border-radius: var(--radius-full);
  background: #e2e8f0;
  color: #475569;
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
}

.inspector-tab.is-active .tab-count {
  background: var(--color-primary-100);
  color: var(--color-primary-700);
}

.inspector-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.section-title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
  letter-spacing: 0.02em;
}

.section-hint {
  font-size: 11px;
  color: #94a3b8;
}

.clear-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: none;
  background: transparent;
  color: var(--color-primary-600);
  font-size: 11.5px;
  font-weight: 500;
  padding: 0;
}

.clear-link:hover {
  color: var(--color-primary-700);
}

.member-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.member-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 5px;
  border-radius: var(--radius-full);
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: var(--color-text-body);
  font-size: 12px;
  transition: all var(--transition-fast);
}

.member-chip:hover {
  border-color: #bae6fd;
  background: var(--color-primary-50);
}

.member-chip.is-active {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  color: var(--color-primary-900);
  font-weight: 600;
}

.member-name {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: #e2e8f0;
  color: #475569;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 11px;
  border-radius: var(--radius-lg);
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.task-card:hover,
.task-card.is-hovered {
  background: var(--color-surface-white);
  border-color: #7dd3fc;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.08);
}

.task-card.is-pinned {
  background: var(--color-primary-50);
  border-color: var(--color-primary-500);
  box-shadow: 0 2px 8px rgba(14, 165, 233, 0.14);
}

.task-card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.task-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #94a3b8;
  flex-shrink: 0;
}

.task-status-dot.is-live {
  background: var(--color-accent-emerald);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.16);
}

.task-name {
  flex: 1;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-text-title);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pin-indicator {
  color: var(--color-primary-600);
  display: inline-flex;
}

.task-meta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.status-pill {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 600;
}

.status-pill.is-running {
  background: #ecfdf5;
  color: #047857;
}

.status-pill.is-completed {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

.status-pill.is-failed {
  background: #fef2f2;
  color: #b91c1c;
}

.status-pill.is-neutral {
  background: #f1f5f9;
  color: #475569;
}

.task-author,
.task-scope {
  font-size: 11px;
}

.req-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.req-tag {
  max-width: 100%;
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid #e0f2fe;
  background: #ffffff;
  color: var(--color-primary-700);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.req-tag:hover {
  border-color: var(--color-primary-500);
}

.task-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding-top: 2px;
}

.task-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.card-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 5px;
  border: 1px solid #e2e8f0;
  background: var(--color-surface-white);
  color: #475569;
  font-size: 11px;
  transition: all var(--transition-fast);
}

.card-action-btn:hover {
  border-color: var(--color-primary-500);
  color: var(--color-primary-700);
}

.mini-icon {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

.churn-nums {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}

.num-add {
  color: #059669;
}

.num-del {
  color: #e11d48;
}

.entity-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.entity-title-wrap {
  min-width: 0;
  flex: 1;
}

.entity-repo-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
  font-size: 11.5px;
  color: var(--color-text-muted);
}

.repo-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex-shrink: 0;
}

.entity-repo-name {
  font-weight: 600;
  color: var(--color-text-body);
}

.entity-branch {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: #64748b;
}

.entity-name {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-primary-900);
  word-break: break-word;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: #f8fafc;
  border: 1px solid #f1f5f9;
}

.metric-label {
  font-size: 11px;
  color: var(--color-text-muted);
}

.metric-val {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text-title);
}

.metric-val.is-primary {
  color: var(--color-primary-600);
}

.mini-sparkline {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 36px;
  padding: 6px 8px;
  border-radius: var(--radius-md);
  background: #f8fafc;
  border: 1px solid #f1f5f9;
}

.mini-spark-col {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
}

.mini-spark-bar {
  width: 100%;
  border-radius: 2px 2px 0 0;
  background: #e2e8f0;
}

.mini-spark-bar.has-data {
  background: var(--color-primary-500);
}

.compact-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.compact-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  background: #f8fafc;
  text-align: left;
  font-size: 12px;
  color: var(--color-text-body);
  transition: all var(--transition-fast);
}

.compact-row.is-clickable {
  cursor: pointer;
}

.compact-row.is-clickable:hover {
  background: var(--color-primary-50);
  border-color: #bae6fd;
  color: var(--color-primary-900);
}

.compact-main {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 8px;
  border-radius: var(--radius-md);
  background: #f8fafc;
}

.file-icon {
  width: 14px;
  height: 14px;
  color: var(--color-primary-500);
  flex-shrink: 0;
}

.file-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.file-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-title);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-sub {
  font-family: var(--font-mono);
  font-size: 10px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-stats {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}

.mono-dim {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #64748b;
}

.commit-pill {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--color-primary-100);
  color: var(--color-primary-700);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
}

.commit-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.commit-row {
  padding: 7px 9px;
  border-radius: var(--radius-md);
  background: #f8fafc;
  border: 1px solid #f1f5f9;
}

.commit-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}

.commit-icon {
  width: 12px;
  height: 12px;
  color: var(--color-primary-500);
  flex-shrink: 0;
}

.commit-hash {
  font-size: 10.5px;
  color: var(--color-primary-700);
}

.commit-date {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: #94a3b8;
}

.commit-churn {
  margin-left: auto;
}

.commit-subject {
  margin: 0;
  font-size: 11.5px;
  color: var(--color-text-body);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.empty-hint {
  font-size: 12px;
  color: #94a3b8;
  padding: 6px 2px;
}

.detail-empty {
  padding-top: 24px;
}

@media (max-width: 1024px) {
  .diorama-inspector {
    width: 100%;
    border-left: none;
    border-top: 1px solid #e2e8f0;
    max-height: 360px;
  }

  .diorama-inspector.is-collapsed {
    width: 100%;
    height: 36px;
  }

  .collapse-handle {
    display: none;
  }
}
</style>
