import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchRequirementOptions } from '@/services/requirementOptions'
import type { RequirementOption, TaskRailView } from '@/types/taskRail'

export const useTaskRailStore = defineStore('taskRail', () => {
  const view = ref<TaskRailView>('all')
  const selectedRequirement = ref<RequirementOption | null>(null)
  const requirements = ref<RequirementOption[]>([])
  const pinnedIds = ref<string[]>([])
  const recentIds = ref<string[]>([])
  const workspaceId = ref('')
  let scope = ''
  let generation = 0
  let loaded = false
  let pendingLoad: Promise<void> | null = null
  const storageKey = () => `task-rail:${scope}`

  function persist() {
    try { localStorage.setItem(storageKey(), JSON.stringify({ pinnedIds: pinnedIds.value, recentIds: recentIds.value })) } catch { /* Optional local preference. */ }
  }

  function setContext(wsId: string, userId: string) {
    const nextScope = `${location.origin}:${userId}:${wsId}`
    if (nextScope === scope) return
    scope = nextScope
    workspaceId.value = wsId
    generation++
    loaded = false
    pendingLoad = null
    view.value = 'all'
    selectedRequirement.value = null
    requirements.value = []
    pinnedIds.value = []
    recentIds.value = []
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey()) || '{}')
      const ids = (value: unknown) => Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === 'string'))].slice(0, 2) : []
      pinnedIds.value = ids(saved.pinnedIds)
      recentIds.value = ids(saved.recentIds)
    } catch { /* Start with current workspace defaults. */ }
  }

  function remember(requirement: RequirementOption) {
    requirements.value = [requirement, ...requirements.value.filter((item) => item.id !== requirement.id)]
  }

  async function loadSlots() {
    if (loaded || !workspaceId.value) return
    if (pendingLoad) return pendingLoad
    const seq = generation
    const wsId = workspaceId.value
    const savedIds = [...new Set([...pinnedIds.value, ...recentIds.value])]
    pendingLoad = (async () => {
      try {
        const [latest, saved] = await Promise.all([
          fetchRequirementOptions(wsId, { page_size: 2 }),
          savedIds.length ? fetchRequirementOptions(wsId, { ids: savedIds.join(',') }) : Promise.resolve({ items: [] }),
        ])
        if (generation !== seq) return
        const merged = new Map([...latest.items, ...saved.items, ...requirements.value].map((item) => [item.id, item]))
        requirements.value = [...merged.values()]
        const valid = new Set(requirements.value.map((item) => item.id))
        pinnedIds.value = pinnedIds.value.filter((id) => valid.has(id))
        recentIds.value = [...new Set([...recentIds.value.filter((id) => valid.has(id)), ...latest.items.map((item) => item.id)])].slice(0, 2)
        loaded = true
        persist()
      } finally {
        if (generation === seq) pendingLoad = null
      }
    })()
    return pendingLoad
  }

  const slots = computed(() => {
    const ids = [...new Set([...pinnedIds.value, ...recentIds.value])].slice(0, 2)
    const selected = selectedRequirement.value
    if (view.value === 'requirement' && selected && !ids.includes(selected.id)) {
      if (ids.length === 2) ids[1] = selected.id
      else ids.push(selected.id)
    }
    return [0, 1].map((index) => requirements.value.find((item) => item.id === ids[index]) || null)
  })

  function selectView(next: Exclude<TaskRailView, 'requirement'>) {
    view.value = next
    selectedRequirement.value = null
  }

  function selectRequirement(requirement: RequirementOption) {
    remember(requirement)
    recentIds.value = [requirement.id, ...recentIds.value.filter((id) => id !== requirement.id)].slice(0, 2)
    selectedRequirement.value = requirement
    view.value = 'requirement'
    persist()
  }

  function togglePin(requirement: RequirementOption) {
    remember(requirement)
    if (pinnedIds.value.includes(requirement.id)) pinnedIds.value = pinnedIds.value.filter((id) => id !== requirement.id)
    else pinnedIds.value = [...pinnedIds.value, requirement.id].slice(-2)
    persist()
  }

  return { view, selectedRequirement, slots, pinnedIds, setContext, loadSlots, selectView, selectRequirement, togglePin }
})
