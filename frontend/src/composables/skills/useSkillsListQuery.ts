import { computed, ref, type Ref } from 'vue'
import api from '@/utils/api'

export type SkillDimension = 'GLOBAL' | 'WORKSPACE'

export type SkillItem = {
  id: string
  name: string
  description: string | null
  dimension: SkillDimension
  workspace_id: string | null
  creator_id: string
  creator_display_name: string | null
  last_modifier_id: string | null
  last_modifier_display_name: string | null
  last_modified_at: string | null
  can_manage: boolean
  source_type?: string | null
  source_repo_url?: string | null
  source_skill_name?: string | null
  source_subdir?: string | null
  source_locked?: boolean
  source_commit_sha?: string | null
  source_last_synced_at?: string | null
  publish_state?: 'PUBLISHED' | 'DRAFT'
  has_pending_changes?: boolean
  changed_files_count?: number
  latest_version_no: number
  average_score: number | null
  review_count: number
}

type SkillScope = 'all' | 'global' | 'workspace'

type UseSkillsListQueryOptions = {
  activeScope: Ref<SkillScope>
  skillNameKeyword: Ref<string>
  workspaceFilterId: Ref<string>
  pageSize?: number
}

type LoadSkillListOptions = {
  resetPage?: boolean
}

export function useSkillsListQuery(options: UseSkillsListQueryOptions) {
  const loading = ref(false)
  const skills = ref<SkillItem[]>([])
  const skillPage = ref(1)
  const skillTotal = ref(0)
  const skillPageSize = Number(options.pageSize || 20)

  const skillTotalPages = computed(() => {
    if (skillTotal.value <= 0) return 1
    return Math.max(1, Math.ceil(skillTotal.value / skillPageSize))
  })

  const loadSkills = async (loadOptions?: LoadSkillListOptions) => {
    if (loadOptions?.resetPage) {
      skillPage.value = 1
    }

    loading.value = true
    try {
      const keyword = options.skillNameKeyword.value.trim()
      const params: Record<string, unknown> = {
        scope: options.activeScope.value,
        keyword: keyword || undefined,
        page: skillPage.value,
        page_size: skillPageSize,
      }
      if (options.activeScope.value === 'workspace') {
        const targetWorkspaceId = String(options.workspaceFilterId.value || '').trim()
        if (targetWorkspaceId) {
          params.workspace_id = targetWorkspaceId
        }
      }
      const res = await api.get('/skills', {
        params,
      })
      skills.value = Array.isArray(res.data?.items) ? res.data.items : []
      skillTotal.value = Number(res.data?.total || 0)

      const totalPages = Math.max(1, Math.ceil((skillTotal.value || 0) / skillPageSize))
      if (skillPage.value > totalPages) {
        skillPage.value = totalPages
      }
    } catch (error) {
      console.error('Failed to load skills', error)
      skills.value = []
      skillTotal.value = 0
    } finally {
      loading.value = false
    }
  }

  const prevSkillPage = async () => {
    if (loading.value || skillPage.value <= 1) return
    skillPage.value -= 1
    await loadSkills()
  }

  const nextSkillPage = async () => {
    if (loading.value || skillPage.value >= skillTotalPages.value) return
    skillPage.value += 1
    await loadSkills()
  }

  return {
    loading,
    skills,
    skillPage,
    skillPageSize,
    skillTotal,
    skillTotalPages,
    loadSkills,
    prevSkillPage,
    nextSkillPage,
  }
}
