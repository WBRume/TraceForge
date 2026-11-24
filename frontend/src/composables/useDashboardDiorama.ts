import { computed, onScopeDispose, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'
import api from '@/utils/api'
import type {
  DashboardDioramaPayload,
  DioramaDrillState,
  DioramaHit,
  DioramaIsoMode,
  DioramaMetric,
  DioramaModuleHeatStats,
  DioramaModuleItem,
  DioramaRepoItem,
  DioramaSearchEntry,
  DioramaWindowMode,
} from '@/types/dashboardDiorama'

export function useDashboardDiorama(workspaceIdSource: MaybeRefOrGetter<string>) {
  const payload = shallowRef<DashboardDioramaPayload | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef(false)
  const days = shallowRef<14 | 30 | 60>(30)

  const metric = shallowRef<DioramaMetric>('heat')
  const isoMode = shallowRef<DioramaIsoMode>('3d')
  const windowMode = shallowRef<DioramaWindowMode>('cumulative')
  const dayIndex = shallowRef(0)
  const zoomPct = shallowRef(100)
  const showAvatars = shallowRef(true)
  const showLabels = shallowRef(true)

  const enabledRepoIds = shallowRef<Set<string>>(new Set())
  const pinnedTaskId = shallowRef<string | null>(null)
  const hoveredTaskId = shallowRef<string | null>(null)
  const activeMemberId = shallowRef<string | null>(null)
  const selectedHit = shallowRef<DioramaHit | null>(null)
  const drill = shallowRef<DioramaDrillState | null>(null)

  const playing = shallowRef(false)
  const speedIdx = shallowRef(0)
  const speeds = [1, 2, 4] as const
  let playTimer: number | undefined
  let fetchSeq = 0

  const speedLabel = computed(() => `${speeds[speedIdx.value]}×`)

  const activeTaskId = computed(() => hoveredTaskId.value || pinnedTaskId.value)
  const effectiveMemberId = computed(() => (activeTaskId.value ? null : activeMemberId.value))

  const moduleHeatMap = computed(() => {
    const map = new Map<string, DioramaModuleHeatStats>()
    const data = payload.value
    if (!data) return map

    if (data.timeline.length) {
      const endIdx = Math.min(Math.max(0, dayIndex.value), data.timeline.length - 1)
      const startIdx = windowMode.value === 'day' ? endIdx : 0
      for (let i = startIdx; i <= endIdx; i++) {
        const day = data.timeline[i]
        if (!day) continue
        const recency = windowMode.value === 'day' ? 1 : 0.42 + 0.58 * ((i + 1) / (endIdx + 1))
        for (const [mid, st] of Object.entries(day.module_heat || {})) {
          const prev = map.get(mid) ?? { commits: 0, added: 0, deleted: 0, score: 0 }
          prev.commits += st.commits
          prev.added += st.added
          prev.deleted += st.deleted
          prev.score += (st.commits * 1.8 + Math.log1p(st.added + st.deleted) * 0.65) * recency
          map.set(mid, prev)
        }
      }
      return map
    }

    for (const repo of data.repos) {
      for (const mod of repo.modules) {
        if (mod.commits > 0) {
          map.set(mod.id, {
            commits: mod.commits,
            added: mod.added,
            deleted: mod.deleted,
            score: mod.commits * 1.8 + Math.log1p(mod.added + mod.deleted) * 0.65,
          })
        }
      }
    }
    return map
  })

  const peakModule = computed<{
    repo: DioramaRepoItem
    module: DioramaModuleItem
    stats: DioramaModuleHeatStats
  } | null>(() => {
    const data = payload.value
    if (!data) return null
    let best: { repo: DioramaRepoItem; module: DioramaModuleItem; stats: DioramaModuleHeatStats } | null = null
    const enabled = enabledRepoIds.value
    for (const repo of data.repos) {
      if (!enabled.has(repo.id)) continue
      for (const mod of repo.modules) {
        const st = moduleHeatMap.value.get(mod.id)
        if (!st || st.commits <= 0) continue
        if (!best || st.score > best.stats.score) {
          best = { repo, module: mod, stats: st }
        }
      }
    }
    return best
  })

  const searchCorpus = computed<DioramaSearchEntry[]>(() => {
    const data = payload.value
    if (!data) return []
    const entries: DioramaSearchEntry[] = []
    for (const repo of data.repos) {
      for (const mod of repo.modules) {
        entries.push({
          kind: 'module',
          moduleId: mod.id,
          name: mod.name,
          path: `${repo.name}/${mod.name}`,
          loc: mod.loc,
          commits: mod.commits,
        })
        for (const f of mod.files) {
          if (f.is_aggregate) continue
          entries.push({
            kind: 'file',
            moduleId: mod.id,
            name: f.name,
            path: `${repo.name}/${f.path}`,
            loc: f.loc,
            commits: f.commits,
          })
        }
      }
    }
    return entries
  })

  function stopPlayback() {
    playing.value = false
    if (playTimer !== undefined) {
      window.clearTimeout(playTimer)
      playTimer = undefined
    }
  }

  async function load(refresh = false) {
    const wsId = toValue(workspaceIdSource)
    if (!wsId) return
    const seq = ++fetchSeq
    loading.value = true
    stopPlayback()
    try {
      const res = await api.get<DashboardDioramaPayload>(`/workspaces/${wsId}/dashboard/repo-diorama`, {
        params: { days: days.value, refresh },
      })
      if (seq !== fetchSeq) return
      payload.value = res.data
      enabledRepoIds.value = new Set(res.data.repos.map(r => r.id))
      dayIndex.value = Math.max(0, res.data.timeline.length - 1)
      selectedHit.value = null
      drill.value = null
      pinnedTaskId.value = null
      hoveredTaskId.value = null
      activeMemberId.value = null
      error.value = false
    } catch (err) {
      if (seq !== fetchSeq) return
      console.error('Failed to load repository diorama', err)
      error.value = true
    } finally {
      if (seq === fetchSeq) loading.value = false
    }
  }

  function toggleRepo(repoId: string) {
    const next = new Set(enabledRepoIds.value)
    if (next.has(repoId)) {
      if (next.size <= 1) return
      next.delete(repoId)
    } else {
      next.add(repoId)
    }
    enabledRepoIds.value = next
  }

  function ensureRepoEnabled(repoId: string) {
    if (enabledRepoIds.value.has(repoId)) return
    const next = new Set(enabledRepoIds.value)
    next.add(repoId)
    enabledRepoIds.value = next
  }

  function toggleMember(memberId: string) {
    pinnedTaskId.value = null
    activeMemberId.value = activeMemberId.value === memberId ? null : memberId
  }

  function togglePinTask(taskId: string) {
    activeMemberId.value = null
    pinnedTaskId.value = pinnedTaskId.value === taskId ? null : taskId
  }

  function clearFocus() {
    pinnedTaskId.value = null
    hoveredTaskId.value = null
    activeMemberId.value = null
  }

  function setDay(index: number) {
    const maxIdx = Math.max(0, (payload.value?.timeline.length ?? 1) - 1)
    dayIndex.value = Math.max(0, Math.min(maxIdx, index))
  }

  function cycleSpeed() {
    speedIdx.value = (speedIdx.value + 1) % speeds.length
  }

  function scheduleNextTick() {
    if (!playing.value) return
    const delay = Math.round(760 / speeds[speedIdx.value])
    playTimer = window.setTimeout(() => {
      if (!playing.value) return
      const maxIdx = Math.max(0, (payload.value?.timeline.length ?? 1) - 1)
      if (dayIndex.value >= maxIdx) {
        stopPlayback()
        return
      }
      dayIndex.value += 1
      scheduleNextTick()
    }, delay)
  }

  function togglePlayback() {
    const len = payload.value?.timeline.length ?? 0
    if (len < 2) return
    if (playing.value) {
      stopPlayback()
      return
    }
    if (dayIndex.value >= len - 1) dayIndex.value = 0
    playing.value = true
    scheduleNextTick()
  }

  watch(() => [toValue(workspaceIdSource), days.value] as const, () => {
    void load(false)
  }, { immediate: true })

  onScopeDispose(() => {
    stopPlayback()
  })

  return {
    payload,
    loading,
    error,
    days,
    metric,
    isoMode,
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
  }
}
