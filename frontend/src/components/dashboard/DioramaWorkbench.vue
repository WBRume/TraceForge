<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, shallowRef, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { MessageSquare, RefreshCw, TrendingUp, X } from '@/components/icons'
import { useDashboardDiorama } from '@/composables/useDashboardDiorama'
import { ArchitecturalDioramaEngine } from '@/utils/dioramaEngine'
import type { DioramaHit, DioramaModuleItem, DioramaRepoItem } from '@/types/dashboardDiorama'
import DioramaToolbar from './DioramaToolbar.vue'
import DioramaTimelineBar from './DioramaTimelineBar.vue'
import DioramaInspector from './DioramaInspector.vue'
import DioramaSpatialTheater from './DioramaSpatialTheater.vue'

const props = defineProps<{
  workspaceId: string
}>()

const { t, locale } = useI18n()
const router = useRouter()

const {
  payload,
  loading,
  error,
  days,
  metric,
  stageMode,
  isoMode,
  theaterAutoplay,
  windowMode,
  dayIndex,
  zoomPct,
  showAvatars,
  showLabels,
  enabledRepoIds,
  pinnedTaskId,
  hoveredTaskId,
  activeMemberId,
  activeTaskId,
  effectiveMemberId,
  moduleHeatMap,
  peakModule,
  selectedHit,
  drill,
  playing,
  speedLabel,
  searchCorpus,
  load,
  toggleRepo,
  ensureRepoEnabled,
  toggleMember,
  togglePinTask,
  clearFocus,
  setDay,
  cycleSpeed,
  togglePlayback,
  stopPlayback,
} = useDashboardDiorama(() => props.workspaceId)

const canvasRef = shallowRef<HTMLCanvasElement | null>(null)
const viewportRef = shallowRef<HTMLDivElement | null>(null)
const engineRef = shallowRef<ArchitecturalDioramaEngine | null>(null)
const theaterRef = useTemplateRef<InstanceType<typeof DioramaSpatialTheater>>('theaterRef')
const inspectorCollapsed = shallowRef(false)

const hoverState = shallowRef<{ hit: DioramaHit; x: number; y: number } | null>(null)
let searchMatches = new Set<string>()

const hasRepos = computed(() => {
  const data = payload.value
  if (!data) return false
  if (typeof data.has_repositories === 'boolean') return data.has_repositories
  return data.repos.length > 0
})
const showTheater = computed(() => Boolean(payload.value && (!hasRepos.value || stageMode.value === 'theater')))
const showDioramaCanvas = computed(() => Boolean(hasRepos.value && stageMode.value !== 'theater'))
const visibleTasks = computed(() => {
  const tasks = payload.value?.tasks ?? []
  if (!showTheater.value || !hasRepos.value) return tasks
  return tasks.filter(task => !task.repos.length || task.repos.some(id => enabledRepoIds.value.has(id)))
})

const pinnedTask = computed(() => {
  if (!pinnedTaskId.value || !payload.value) return null
  return payload.value.tasks.find(item => item.id === pinnedTaskId.value) ?? null
})

const focusedMember = computed(() => {
  if (!effectiveMemberId.value || !payload.value) return null
  return payload.value.members.find(item => item.id === effectiveMemberId.value) ?? null
})

const tooltipStyle = computed(() => {
  const hs = hoverState.value
  const vp = viewportRef.value
  if (!hs || !vp) return {}
  const maxX = Math.max(12, vp.clientWidth - 260)
  const maxY = Math.max(12, vp.clientHeight - 130)
  const left = Math.min(maxX, Math.max(12, hs.x + 16))
  const top = Math.min(maxY, Math.max(12, hs.y + 16))
  return { left: `${left}px`, top: `${top}px` }
})

const hoveredHeat = computed(() => {
  const hit = hoverState.value?.hit
  if (!hit || hit.kind !== 'module' || !hit.module) return null
  return moduleHeatMap.value.get(hit.module.id)
})

function formatLoc(loc: number): string {
  return loc >= 1000 ? `${(loc / 1000).toFixed(1)}k` : String(loc)
}

function disposeEngine() {
  if (engineRef.value) {
    engineRef.value.destroy()
    engineRef.value = null
  }
}

function ensureEngine() {
  const data = payload.value
  const canvas = canvasRef.value
  const viewport = viewportRef.value
  if (!data || !showDioramaCanvas.value || !canvas || !viewport) {
    disposeEngine()
    return
  }

  if (!engineRef.value) {
    engineRef.value = new ArchitecturalDioramaEngine(canvas, viewport, data, {
      pendingRepoLabel: t('dashboard.diorama.repo_pending'),
      onZoomChange: pct => { zoomPct.value = pct },
      onDrillChange: next => { drill.value = next },
      onHover: (hit, sx, sy) => {
        hoverState.value = hit ? { hit, x: sx, y: sy } : null
      },
      onSelect: hit => {
        selectedHit.value = hit
        if (inspectorCollapsed.value) inspectorCollapsed.value = false
      },
    })
    if (enabledRepoIds.value.size !== data.repos.length) {
      engineRef.value.setEnabledRepos(enabledRepoIds.value)
    }
    if (searchMatches.size) engineRef.value.setSearchMatches(searchMatches)
  } else {
    engineRef.value.setData(data, enabledRepoIds.value)
  }

  const eng = engineRef.value
  eng.setMetric(metric.value)
  eng.setIsoMode(isoMode.value)
  eng.setLayers({ avatars: showAvatars.value, labels: showLabels.value })
  eng.setTimeline(dayIndex.value, windowMode.value, false)
  eng.setHighlight(activeTaskId.value, effectiveMemberId.value)
}

watch([showDioramaCanvas, payload, enabledRepoIds], ([visible, data, ids], [wasVisible, previous]) => {
  if (!visible || !wasVisible || data !== previous) {
    hoverState.value = null
    ensureEngine()
  } else {
    engineRef.value?.setEnabledRepos(ids)
  }
}, { flush: 'post' })

watch(showTheater, visible => {
  if (!visible) return
  stopPlayback()
  selectedHit.value = null
  drill.value = null
})

watch(visibleTasks, tasks => {
  if (pinnedTaskId.value && !tasks.some(task => task.id === pinnedTaskId.value)) pinnedTaskId.value = null
  if (hoveredTaskId.value && !tasks.some(task => task.id === hoveredTaskId.value)) hoveredTaskId.value = null
})

watch(locale, () => {
  engineRef.value?.setPendingRepoLabel(t('dashboard.diorama.repo_pending'))
})

watch(metric, val => engineRef.value?.setMetric(val))
watch(isoMode, val => engineRef.value?.setIsoMode(val))
watch([showAvatars, showLabels], ([avatars, labels]) => {
  engineRef.value?.setLayers({ avatars, labels })
})
watch([dayIndex, windowMode], ([idx, mode]) => {
  engineRef.value?.setTimeline(idx, mode, playing.value)
})
watch([activeTaskId, effectiveMemberId], ([taskId, memberId]) => {
  engineRef.value?.setHighlight(taskId, memberId)
})

function handleFocusRepo(repoId: string) {
  ensureRepoEnabled(repoId)
  nextTick(() => {
    engineRef.value?.focusEntity('repo', repoId)
  })
}

function handleFocusEntity(kind: 'repo' | 'module', id: string) {
  if (kind === 'module' && payload.value) {
    const parentRepo = payload.value.repos.find(r => r.modules.some(m => m.id === id))
    if (parentRepo) ensureRepoEnabled(parentRepo.id)
  } else if (kind === 'repo') {
    ensureRepoEnabled(id)
  }
  nextTick(() => {
    engineRef.value?.focusEntity(kind, id)
  })
}

function handleSelectModule(repo: DioramaRepoItem, mod: DioramaModuleItem) {
  ensureRepoEnabled(repo.id)
  selectedHit.value = { kind: 'module', id: mod.id, repo, module: mod }
  nextTick(() => {
    engineRef.value?.focusEntity('module', mod.id)
  })
}

function handleSearchChange(moduleIds: Set<string>) {
  searchMatches = moduleIds
  engineRef.value?.setSearchMatches(moduleIds)
}

function handleSelectSearchModule(moduleId: string) {
  handleFocusEntity('module', moduleId)
}

function handleResetView() {
  engineRef.value?.resetView(false)
}

function handleDaysChange(next: typeof days.value) {
  if (next !== days.value) days.value = next
  else if (error.value) void load()
}

function clearTaskFocus() {
  pinnedTaskId.value = null
  hoveredTaskId.value = null
}

function handleKeydown(e: KeyboardEvent) {
  if (e.defaultPrevented || e.ctrlKey || e.altKey || e.metaKey) return
  const target = e.target
  if (target instanceof HTMLElement && target.isContentEditable) return
  if (target instanceof Element && target.closest('input, textarea, select, [role="textbox"]')) return
  if (e.key === ' ' && target instanceof Element && target.closest('button, a[href], [role="button"], [role="tab"]')) return

  if (showTheater.value) {
    if (e.key === ' ') {
      e.preventDefault()
      if (!e.repeat) theaterAutoplay.value = !theaterAutoplay.value
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      if (theaterRef.value?.step(e.key === 'ArrowLeft' ? -1 : 1)) e.preventDefault()
    } else if (e.key === 'Escape') {
      clearFocus()
    }
    return
  }
  if (!engineRef.value) return

  if (e.key === 'q' || e.key === 'Q') {
    engineRef.value.rotateView(-1)
  } else if (e.key === 'e' || e.key === 'E') {
    engineRef.value.rotateView(1)
  } else if (e.key === 'v' || e.key === 'V') {
    stageMode.value = stageMode.value === '3d' ? 'top' : '3d'
  } else if (e.key === '0') {
    handleResetView()
  } else if (e.key === ' ' && (payload.value?.timeline.length ?? 0) > 1) {
    e.preventDefault()
    togglePlayback()
  } else if (e.key === 'ArrowLeft') {
    setDay(dayIndex.value - 1)
  } else if (e.key === 'ArrowRight') {
    setDay(dayIndex.value + 1)
  } else if (e.key === 'Escape') {
    if (pinnedTaskId.value || activeMemberId.value) {
      clearFocus()
    } else {
      handleResetView()
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  ensureEngine()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  disposeEngine()
})
</script>

<template>
  <section class="diorama-workbench" :aria-busy="loading">
    <DioramaToolbar
      :ready="Boolean(payload)"
      :workspace-name="payload?.workspace_name ?? ''"
      :has-repos="hasRepos"
      :repos="payload?.repos ?? []"
      :enabled-repo-ids="enabledRepoIds"
      :metric="metric"
      :days="payload?.days ?? days"
      :stage-mode="stageMode"
      :theater-autoplay="theaterAutoplay"
      :zoom-pct="zoomPct"
      :show-avatars="showAvatars"
      :show-labels="showLabels"
      :loading="loading"
      :search-corpus="searchCorpus"
      @toggle-repo="toggleRepo"
      @focus-repo="handleFocusRepo"
      @update:metric="metric = $event"
      @update:days="handleDaysChange"
      @update:stage-mode="stageMode = $event"
      @update:theater-autoplay="theaterAutoplay = $event"
      @update:show-avatars="showAvatars = $event"
      @update:show-labels="showLabels = $event"
      @rotate="engineRef?.rotateView($event)"
      @zoom="engineRef?.zoomBy($event)"
      @reset-view="handleResetView"
      @refresh="load({ refresh: true })"
      @search-change="handleSearchChange"
      @select-search-module="handleSelectSearchModule"
    />

    <div v-if="error && payload" class="update-error" role="alert">
      <span>{{ t('dashboard.diorama.load_failed') }}</span>
      <el-button size="small" @click="load({ refresh: true })">{{ t('dashboard.retry') }}</el-button>
    </div>

    <div class="workbench-body">
      <div class="stage-column">
        <div v-if="showDioramaCanvas" ref="viewportRef" class="diorama-stage">
          <canvas ref="canvasRef" class="diorama-canvas" />

          <!-- Top-left HUD: Drill breadcrumbs & Peak Module -->
          <div v-if="hasRepos" class="hud-top-left">
            <nav class="breadcrumb-pill" :aria-label="t('dashboard.diorama.breadcrumb_label')">
              <button
                type="button"
                class="crumb-btn"
                :class="{ 'is-current': !drill }"
                @click="handleResetView"
              >
                {{ t('dashboard.diorama.all_repos') }}
              </button>
              <template v-if="drill">
                <span class="crumb-sep">/</span>
                <button
                  type="button"
                  class="crumb-btn"
                  :class="{ 'is-current': !drill.module }"
                  @click="handleFocusRepo(drill.repo.id)"
                >
                  {{ drill.repo.name }}
                </button>
              </template>
              <template v-if="drill?.module">
                <span class="crumb-sep">/</span>
                <span class="crumb-current">{{ drill.module.name }}</span>
              </template>
            </nav>

            <button
              v-if="peakModule"
              type="button"
              class="peak-pill"
              :title="t('dashboard.diorama.peak_tooltip')"
              @click="handleSelectModule(peakModule.repo, peakModule.module)"
            >
              <TrendingUp class="peak-icon" />
              <span class="peak-label">{{ t('dashboard.diorama.peak_label') }}</span>
              <strong class="peak-name">{{ peakModule.repo.name }}/{{ peakModule.module.name }}</strong>
              <span class="peak-stat">{{ peakModule.stats.commits }}c</span>
            </button>
          </div>

          <!-- Top-center Focus Banner -->
          <div v-if="hasRepos && (pinnedTask || focusedMember)" class="hud-focus-banner">
            <template v-if="pinnedTask">
              <span class="focus-dot" />
              <span class="focus-text">
                {{ t('dashboard.diorama.focusing_task', { name: pinnedTask.name }) }}
              </span>
              <button
                type="button"
                class="focus-action-btn"
                @click="router.push({ name: 'taskChat', params: { wsId: workspaceId, taskId: pinnedTask.id } })"
              >
                <MessageSquare class="mini-icon" />
                <span>{{ t('dashboard.diorama.open_chat_short') }}</span>
              </button>
            </template>
            <template v-else-if="focusedMember">
              <span class="focus-dot" :style="{ backgroundColor: focusedMember.color }" />
              <span class="focus-text">
                {{ t('dashboard.diorama.focusing_member', { name: focusedMember.display_name }) }}
              </span>
            </template>
            <button
              type="button"
              class="focus-close-btn"
              :title="t('dashboard.diorama.clear_focus')"
              @click="clearFocus"
            >
              <X class="mini-icon" />
            </button>
          </div>

          <!-- Bottom-left Subtle Architectural Legend -->
          <div v-if="hasRepos" class="hud-legend">
            <div class="legend-scale">
              <span class="legend-tag">{{ t('dashboard.diorama.legend_calm') }}</span>
              <span class="legend-bar" />
              <span class="legend-tag">{{ t('dashboard.diorama.legend_active') }}</span>
            </div>
            <span class="legend-sep" aria-hidden="true">·</span>
            <span class="legend-hint">{{ t('dashboard.diorama.canvas_hint') }}</span>
          </div>

          <!-- Hover Tooltip Card -->
          <div v-if="hoverState" class="hover-tooltip" :style="tooltipStyle">
            <div class="tip-head">
              <span class="tip-dot" :style="{ backgroundColor: hoverState.hit.repo.color }" />
              <strong class="tip-title">
                {{
                  hoverState.hit.kind === 'module' && hoverState.hit.module
                    ? `${hoverState.hit.repo.name} / ${hoverState.hit.module.name}`
                    : hoverState.hit.repo.name
                }}
              </strong>
            </div>

            <div v-if="hoverState.hit.kind === 'module' && hoverState.hit.module" class="tip-grid">
              <span>{{ t('dashboard.diorama.stat_loc') }}</span>
              <strong>{{ formatLoc(hoverState.hit.module.loc) }}</strong>
              <span>{{ t('dashboard.diorama.stat_files') }}</span>
              <strong>{{ hoverState.hit.module.file_count }}</strong>
              <span>{{ t('dashboard.diorama.stat_commits') }}</span>
              <strong class="is-primary">{{ hoveredHeat?.commits ?? 0 }}</strong>
              <span>{{ t('dashboard.diorama.stat_churn') }}</span>
              <strong class="tip-churn">
                <span class="num-add">+{{ hoveredHeat?.added ?? 0 }}</span>
                <span class="num-del">-{{ hoveredHeat?.deleted ?? 0 }}</span>
              </strong>
            </div>
            <div v-else class="tip-grid">
              <span>{{ t('dashboard.diorama.stat_loc') }}</span>
              <strong>{{ formatLoc(hoverState.hit.repo.loc) }}</strong>
              <span>{{ t('dashboard.diorama.stat_files') }}</span>
              <strong>{{ hoverState.hit.repo.file_count }}</strong>
              <span>{{ t('dashboard.diorama.stat_modules') }}</span>
              <strong>{{ hoverState.hit.repo.module_count }}</strong>
            </div>
          </div>
        </div>

        <DioramaSpatialTheater
          v-else-if="showTheater"
          ref="theaterRef"
          :workspace-id="workspaceId"
          :tasks="visibleTasks"
          :members="payload?.members ?? []"
          :active-member-id="activeMemberId"
          :pinned-task-id="pinnedTaskId"
          :hovered-task-id="hoveredTaskId"
          :autoplay="theaterAutoplay"
          :has-repos="hasRepos"
          @toggle-pin-task="togglePinTask"
          @clear-task-focus="clearTaskFocus"
        />

        <div v-else v-loading="loading && !payload" class="diorama-stage is-shell">
          <div v-if="error && !payload" class="stage-overlay-state">
            <el-empty :description="t('dashboard.diorama.load_failed')">
              <el-button type="primary" @click="load({ refresh: true })">
                <RefreshCw class="overlay-btn-icon" />
                <span>{{ t('dashboard.retry') }}</span>
              </el-button>
            </el-empty>
          </div>
        </div>

        <DioramaTimelineBar
          v-if="showDioramaCanvas && payload && payload.timeline.length"
          :timeline="payload.timeline"
          :day-index="dayIndex"
          :window-mode="windowMode"
          :playing="playing"
          :speed-label="speedLabel"
          @toggle-play="togglePlayback"
          @step-day="setDay(dayIndex + $event)"
          @set-day="setDay"
          @cycle-speed="cycleSpeed"
          @update:window-mode="windowMode = $event"
        />
      </div>

      <DioramaInspector
        :workspace-id="workspaceId"
        :has-repos="hasRepos"
        :is-theater-mode="showTheater"
        :repos="payload?.repos ?? []"
        :members="payload?.members ?? []"
        :tasks="visibleTasks"
        :timeline="payload?.timeline ?? []"
        :day-index="dayIndex"
        :window-mode="windowMode"
        :module-heat-map="moduleHeatMap"
        :selected-hit="selectedHit"
        :pinned-task-id="pinnedTaskId"
        :hovered-task-id="hoveredTaskId"
        :active-member-id="activeMemberId"
        :collapsed="inspectorCollapsed"
        @toggle-collapse="inspectorCollapsed = !inspectorCollapsed"
        @toggle-member="toggleMember"
        @toggle-pin-task="togglePinTask"
        @hover-task="hoveredTaskId = $event"
        @focus-entity="handleFocusEntity"
        @select-module="handleSelectModule"
        @clear-focus="clearFocus"
      />
    </div>
  </section>
</template>

<style scoped>
.update-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
  font-size: 13px;
}

.diorama-workbench {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 580px;
  border-radius: var(--radius-xl);
  border: 1px solid #e2e8f0;
  background: var(--color-surface-white);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.workbench-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.stage-column {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.diorama-stage {
  position: relative;
  flex: 1;
  min-height: 460px;
  background: #f1f5f9;
  overflow: hidden;
  cursor: grab;
  user-select: none;
}

.diorama-stage.is-shell {
  cursor: default;
}

.diorama-stage.is-pointer {
  cursor: pointer;
}

.diorama-stage.is-dragging {
  cursor: grabbing;
}

.diorama-canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
}

.stage-overlay-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(248, 250, 252, 0.9);
  cursor: default;
}

.overlay-btn-icon {
  width: 14px;
  height: 14px;
  margin-right: 4px;
}

.hud-top-left {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 10;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  pointer-events: none;
}

.breadcrumb-pill,
.peak-pill {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border-radius: var(--radius-full);
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  box-shadow: var(--shadow-sm);
  font-size: 12px;
}

.crumb-btn {
  border: none;
  background: transparent;
  padding: 0;
  color: #64748b;
  font-size: 12px;
  font-weight: 500;
}

.crumb-btn:hover {
  color: var(--color-primary-600);
}

.crumb-btn.is-current,
.crumb-current {
  color: var(--color-primary-900);
  font-weight: 600;
}

.crumb-sep {
  color: #cbd5e1;
}

.peak-pill {
  color: var(--color-text-body);
  transition: border-color var(--transition-fast);
}

.peak-pill:hover {
  border-color: var(--color-primary-500);
}

.peak-icon {
  width: 13px;
  height: 13px;
  color: var(--color-primary-500);
}

.peak-label {
  color: var(--color-text-muted);
}

.peak-name {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--color-primary-900);
}

.peak-stat {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary-600);
}

.hud-focus-banner {
  position: absolute;
  top: 12px;
  right: 14px;
  z-index: 12;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: min(420px, calc(100% - 28px));
  padding: 5px 10px;
  border-radius: var(--radius-full);
  border: 1px solid #7dd3fc;
  background: rgba(240, 249, 255, 0.96);
  backdrop-filter: blur(8px);
  box-shadow: var(--shadow-md);
  font-size: 12px;
  color: var(--color-primary-900);
}

.focus-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--color-primary-500);
  flex-shrink: 0;
}

.focus-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

.focus-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  border: 1px solid #bae6fd;
  background: #ffffff;
  color: var(--color-primary-700);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.focus-action-btn:hover {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
  color: #ffffff;
}

.focus-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #64748b;
  flex-shrink: 0;
}

.focus-close-btn:hover {
  background: rgba(14, 165, 233, 0.14);
  color: var(--color-primary-900);
}

.mini-icon {
  width: 12px;
  height: 12px;
}

.hud-legend {
  position: absolute;
  left: 12px;
  bottom: 10px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(6px);
  font-size: 11px;
  color: var(--color-text-muted);
  pointer-events: none;
}

.legend-scale {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-bar {
  width: 44px;
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(90deg, #e2e8f0 0%, #7dd3fc 52%, #0284c7 100%);
}

.legend-sep {
  color: #cbd5e1;
}

.hover-tooltip {
  position: absolute;
  z-index: 25;
  width: 244px;
  padding: 10px 12px;
  border-radius: var(--radius-lg);
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(10px);
  box-shadow: var(--shadow-lg);
  pointer-events: none;
}

.tip-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 8px;
}

.tip-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex-shrink: 0;
}

.tip-title {
  font-size: 12.5px;
  color: var(--color-primary-900);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tip-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  row-gap: 4px;
  column-gap: 10px;
  font-size: 11.5px;
  color: var(--color-text-muted);
}

.tip-grid strong {
  text-align: right;
  font-family: var(--font-mono);
  color: var(--color-text-title);
}

.tip-grid strong.is-primary {
  color: var(--color-primary-600);
}

.tip-churn {
  display: inline-flex;
  justify-content: flex-end;
  gap: 5px;
}

.num-add {
  color: #059669;
}

.num-del {
  color: #e11d48;
}

@media (max-width: 1024px) {
  .workbench-body {
    flex-direction: column;
  }

  .diorama-stage {
    min-height: 400px;
  }
}
</style>
