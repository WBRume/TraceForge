import { computed, onBeforeUnmount, ref, type ComputedRef, type Ref } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { SkillAnalysis, SkillAnalysisRefKind } from '@/types/skillAnalysis'

type TranslateFn = (key: string, params?: Record<string, unknown>) => string

type UseSkillAnalysisOptions = {
  t: TranslateFn
  actionError: Ref<string>
  skillId: ComputedRef<string | undefined>
  selectedWorkspaceId: Ref<string>
  hasPendingWorktreeChanges: Ref<boolean> | ComputedRef<boolean>
  latestVersionId: Ref<string> | ComputedRef<string>
  viewVersionId: Ref<string> | ComputedRef<string>
}

const TERMINAL_STATUSES = new Set(['SUCCESS', 'FAILED'])

export function useSkillAnalysis(options: UseSkillAnalysisOptions) {
  const {
    t,
    actionError,
    skillId,
    selectedWorkspaceId,
    hasPendingWorktreeChanges,
    latestVersionId,
    viewVersionId,
  } = options

  const latestAnalysis = ref<SkillAnalysis | null>(null)
  const analysisLoading = ref(false)
  const analysisRunning = ref(false)
  const analysisError = ref('')
  let pollTimer: number | null = null

  const targetAnalysisVersionId = computed(() => {
    const viewed = String(viewVersionId.value || '').trim()
    const latest = String(latestVersionId.value || '').trim()
    if (viewed && latest && viewed !== latest) return viewed
    if (!hasPendingWorktreeChanges.value && latest) return latest
    return ''
  })

  const defaultAnalysisRefKind = computed<SkillAnalysisRefKind>(() => {
    if (targetAnalysisVersionId.value) return 'VERSION'
    return 'WORKTREE'
  })

  const clearPollTimer = () => {
    if (pollTimer !== null) {
      window.clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  const analysisParams = () => {
    const params: { workspace_id?: string, ref_kind: SkillAnalysisRefKind, version_id?: string } = {
      ref_kind: defaultAnalysisRefKind.value,
    }
    if (selectedWorkspaceId.value) params.workspace_id = selectedWorkspaceId.value
    if (targetAnalysisVersionId.value) params.version_id = targetAnalysisVersionId.value
    return params
  }

  const applyAnalysis = (payload: SkillAnalysis | null) => {
    latestAnalysis.value = payload
    analysisRunning.value = payload?.status === 'PENDING' || payload?.status === 'RUNNING'
  }

  const loadLatestAnalysis = async () => {
    if (!skillId.value) return
    analysisLoading.value = true
    analysisError.value = ''
    try {
      const res = await api.get(`/skills/${skillId.value}/analyses/latest`, {
        params: analysisParams(),
      })
      applyAnalysis(res.data || null)
    } catch (error) {
      analysisError.value = formatApiError(error, t('skills.editor.analysis_load_failed'), t)
      actionError.value = analysisError.value
    } finally {
      analysisLoading.value = false
    }
  }

  const refreshAnalysisById = async (analysisId: string) => {
    if (!skillId.value || !analysisId) return null
    const res = await api.get(`/skills/${skillId.value}/analyses/${analysisId}`, {
      params: analysisParams(),
    })
    const payload = (res.data || null) as SkillAnalysis | null
    applyAnalysis(payload)
    return payload
  }

  const pollAnalysis = (analysisId: string, remaining = 90) => {
    clearPollTimer()
    if (!analysisId || remaining <= 0) return
    pollTimer = window.setTimeout(async () => {
      try {
        const payload = await refreshAnalysisById(analysisId)
        if (!payload || TERMINAL_STATUSES.has(payload.status)) {
          analysisRunning.value = false
          return
        }
        pollAnalysis(analysisId, remaining - 1)
      } catch (error) {
        analysisError.value = formatApiError(error, t('skills.editor.analysis_load_failed'), t)
        analysisRunning.value = false
      }
    }, 2000)
  }

  const runAnalysis = async (refKind?: SkillAnalysisRefKind) => {
    if (!skillId.value || analysisRunning.value) return
    const resolvedRefKind = refKind || defaultAnalysisRefKind.value
    analysisRunning.value = true
    analysisError.value = ''
    clearPollTimer()
    try {
      const body: { ref_kind: SkillAnalysisRefKind, version_id?: string } = {
        ref_kind: resolvedRefKind,
      }
      if (resolvedRefKind === 'VERSION' && targetAnalysisVersionId.value) {
        body.version_id = targetAnalysisVersionId.value
      }
      const res = await api.post(`/skills/${skillId.value}/analyses`, body, {
        params: analysisParams(),
      })
      const payload = (res.data || null) as SkillAnalysis | null
      applyAnalysis(payload)
      if (payload?.id) pollAnalysis(payload.id)
    } catch (error) {
      analysisError.value = formatApiError(error, t('skills.editor.analysis_start_failed'), t)
      actionError.value = analysisError.value
      analysisRunning.value = false
    }
  }

  const resetAnalysis = () => {
    clearPollTimer()
    latestAnalysis.value = null
    analysisLoading.value = false
    analysisRunning.value = false
    analysisError.value = ''
  }

  onBeforeUnmount(clearPollTimer)

  return {
    latestAnalysis,
    analysisLoading,
    analysisRunning,
    analysisError,
    defaultAnalysisRefKind,
    targetAnalysisVersionId,
    loadLatestAnalysis,
    runAnalysis,
    refreshAnalysisById,
    resetAnalysis,
  }
}
