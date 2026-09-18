import { computed, onBeforeUnmount, shallowRef, type Ref } from 'vue'
import api from '@/utils/api'
import type { SkillSummary } from '../types'

/** 草稿技能：有未发布改动或发布状态为 DRAFT */
export const isDraftSkill = (skill: SkillSummary): boolean =>
  Boolean(skill?.has_pending_changes || skill?.publish_state === 'DRAFT')

const SEARCH_DEBOUNCE_MS = 300
export const SKILL_PAGE_SIZE = 8

/**
 * 技能选择器：服务端分页 + 关键字搜索（300ms 防抖）+ scope 过滤 + 跨页勾选集。
 *
 * 浏览状态（关键字 / 范围 / 页码 / 列表）为选择器私有；
 * 勾选集由调用方（对话框）持有并经 Ref 注入，提交时组装 skill_ids。
 */
export function useTaskSkillPicker(options: {
  wsId: () => string
  selectedIds: Ref<string[]>
}) {
  const { wsId, selectedIds } = options

  const skills = shallowRef<SkillSummary[]>([])
  const loading = shallowRef(false)
  const keyword = shallowRef('')
  const scope = shallowRef<'all' | 'workspace' | 'global'>('all')
  const page = shallowRef(1)
  const total = shallowRef(0)

  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / SKILL_PAGE_SIZE)))
  const hasDrafts = computed(() => skills.value.some(isDraftSkill))
  const isCurrentPageAllSelected = computed(() => {
    if (skills.value.length === 0) return false
    return skills.value.every((s) => selectedIds.value.includes(s.id))
  })

  let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null

  const load = async (targetPage = page.value) => {
    loading.value = true
    page.value = targetPage
    try {
      const res = await api.get('/skills', {
        params: {
          workspace_id: wsId(),
          scope: scope.value,
          keyword: keyword.value.trim(),
          page: page.value,
          page_size: SKILL_PAGE_SIZE,
        },
      })
      skills.value = res.data?.items || []
      total.value = res.data?.total || 0
    } catch (e) {
      console.error('Failed to load skills', e)
      skills.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  const onSearchInput = () => {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
    searchDebounceTimer = setTimeout(() => {
      void load(1)
    }, SEARCH_DEBOUNCE_MS)
  }

  const clearSearch = () => {
    keyword.value = ''
    void load(1)
  }

  const onScopeChange = (next: 'all' | 'workspace' | 'global') => {
    if (scope.value === next) return
    scope.value = next
    void load(1)
  }

  const prevPage = () => {
    if (page.value > 1) void load(page.value - 1)
  }

  const nextPage = () => {
    if (page.value < totalPages.value) void load(page.value + 1)
  }

  const toggleSkill = (skillId: string) => {
    const idx = selectedIds.value.indexOf(skillId)
    if (idx >= 0) {
      selectedIds.value.splice(idx, 1)
    } else {
      selectedIds.value.push(skillId)
    }
  }

  /** 勾选 / 清空当前页全部技能（跨页保留其余勾选） */
  const toggleCurrentPageAll = () => {
    if (isCurrentPageAllSelected.value) {
      const pageIds = new Set(skills.value.map((s) => s.id))
      selectedIds.value = selectedIds.value.filter((id) => !pageIds.has(id))
    } else {
      for (const s of skills.value) {
        if (!selectedIds.value.includes(s.id)) {
          selectedIds.value.push(s.id)
        }
      }
    }
  }

  onBeforeUnmount(() => {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  })

  return {
    skills,
    loading,
    keyword,
    scope,
    page,
    total,
    totalPages,
    hasDrafts,
    isCurrentPageAllSelected,
    load,
    onSearchInput,
    clearSearch,
    onScopeChange,
    prevPage,
    nextPage,
    toggleSkill,
    toggleCurrentPageAll,
  }
}
