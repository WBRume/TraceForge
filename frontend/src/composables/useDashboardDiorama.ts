import { computed, onScopeDispose, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import api, { getApiServerUrl } from '@/utils/api'
import type {
  DashboardDioramaPayload,
  DashboardDioramaResponse,
  DioramaDays,
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

const FRESH_FOR_MS = 60_000
const MAX_CACHED_WORKSPACES = 8
type CachedPeriod = { data: DashboardDioramaPayload; loadedAt: number }
const workspaceCache = new Map<string, Map<number, CachedPeriod>>()
let cacheServer: string | undefined
let cacheToken: string | null = null

function setCacheScope(server: string, token: string | null) {
  if (cacheServer === server && cacheToken === token) return
  workspaceCache.clear()
  cacheServer = server
  cacheToken = token
}

function cacheResponse(response: DashboardDioramaResponse) {
  const { windows, ...selected } = response
  const { workspace_id, workspace_name, members, generated_at } = selected
  const workspace = workspaceCache.get(workspace_id) ?? new Map<number, CachedPeriod>()
  const loadedAt = Date.now()
  workspace.set(selected.days, { data: selected, loadedAt })
  for (const period of Object.values(windows ?? {})) {
    if (period) {
      workspace.set(period.days, { data: { workspace_id, workspace_name, members, generated_at, ...period }, loadedAt })
    }
  }
  workspaceCache.delete(workspace_id)
  workspaceCache.set(workspace_id, workspace)
  if (workspaceCache.size > MAX_CACHED_WORKSPACES) {
    const oldest = workspaceCache.keys().next().value
    if (oldest !== undefined) workspaceCache.delete(oldest)
  }
  return workspace
}

export function useDashboardDiorama(workspaceIdSource: MaybeRefOrGetter<string>) {
  const auth = useAuthStore()
  const server = shallowRef(getApiServerUrl())
  const workspaceId = computed(() => toValue(workspaceIdSource))
  const payload = shallowRef<DashboardDioramaPayload | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef(false)
  const days = shallowRef<DioramaDays>(30)

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
  let activeRequest: AbortController | undefined

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

  function showPeriod(next: DashboardDioramaPayload) {
    if (next === payload.value) return
    const previous = payload.value
    const hidden = new Set(previous?.repos.filter(repo => !enabledRepoIds.value.has(repo.id)).map(repo => repo.id))
    const enabled = next.repos.filter(repo => !hidden.has(repo.id))
    payload.value = next
    enabledRepoIds.value = new Set((enabled.length ? enabled : next.repos).map(repo => repo.id))
    dayIndex.value = Math.max(0, next.timeline.length - 1)
    clearSceneSelection()
  }

  function clearData() {
    payload.value = null
    enabledRepoIds.value = new Set()
    clearSceneSelection()
  }

  async function load({ refresh = false, revalidate = false } = {}) {
    const wsId = workspaceId.value
    const token = auth.token
    const serverUrl = server.value
    if (!wsId || !token) return
    setCacheScope(serverUrl, token)
    stopPlayback()
    error.value = false
    const requestedDays = days.value
    if (!refresh) {
      const cached = workspaceCache.get(wsId)?.get(requestedDays)
      if (cached) {
        showPeriod(cached.data)
        if (!revalidate && Date.now() - cached.loadedAt < FRESH_FOR_MS) return
      }
      // The in-flight response can supply any of the three periods.
      if (activeRequest) return
    }

    activeRequest?.abort()
    const controller = new AbortController()
    activeRequest = controller
    loading.value = true
    let loadAnotherPeriod = false
    try {
      const res = await api.get<DashboardDioramaResponse>(`/workspaces/${wsId}/dashboard/repo-diorama`, {
        params: { days: requestedDays, refresh, include_windows: true },
        signal: controller.signal,
      })
      if (controller.signal.aborted || wsId !== workspaceId.value || token !== auth.token || serverUrl !== server.value) return
      if (res.data.workspace_id !== wsId || res.data.days !== requestedDays) throw new Error('Unexpected dashboard period')
      const periods = cacheResponse(res.data)
      const selected = periods.get(days.value)
      if (selected) showPeriod(selected.data)
      else loadAnotherPeriod = true
    } catch (err) {
      if (controller.signal.aborted) return
      if (isAxiosError(err) && [401, 403, 404].includes(err.response?.status ?? 0)) {
        workspaceCache.delete(wsId)
        clearData()
      }
      console.error('Failed to load repository diorama', err)
      error.value = true
    } finally {
      if (activeRequest === controller) {
        activeRequest = undefined
        loading.value = false
        if (loadAnotherPeriod) void load()
      }
    }
  }

  function clearSceneSelection() {
    selectedHit.value = null
    drill.value = null
    clearFocus()
  }

  function toggleRepo(repoId: string) {
    const next = new Set(enabledRepoIds.value)
    if (next.has(repoId)) {
      if (next.size <= 1) return
      next.delete(repoId)
      if (selectedHit.value?.repo.id === repoId) selectedHit.value = null
      if (drill.value?.repo.id === repoId) drill.value = null
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

  watch([workspaceId, server, () => auth.token], ([, currentServer, token]) => {
    activeRequest?.abort()
    activeRequest = undefined
    loading.value = false
    error.value = false
    clearData()
    setCacheScope(currentServer, token)
    void load({ revalidate: true })
  }, { immediate: true })
  watch(days, () => { void load() })

  const onServerChanged = () => { server.value = getApiServerUrl() }
  window.addEventListener('sdd-server-changed', onServerChanged)

  onScopeDispose(() => {
    window.removeEventListener('sdd-server-changed', onServerChanged)
    activeRequest?.abort()
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
