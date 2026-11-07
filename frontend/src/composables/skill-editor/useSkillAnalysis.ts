import { computed, onBeforeUnmount, ref, watch, type ComputedRef, type Ref } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { SkillAnalysis, SkillAnalysisRefKind } from '@/types/skillAnalysis'
import { useSkillAnalysisStore, isSkillAnalysisRunning } from '@/stores/skillAnalysis'
import { useProvisioningStore } from '@/stores/provisioning'

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

  const store = useSkillAnalysisStore()
  const background = useProvisioningStore()
  const analysisId = ref('')
  const latestAnalysis = computed(() => store.analyses[analysisId.value] || null)
  const analysisLoading = ref(false)
  const submitting = ref(false)
  const analysisRunning = computed(() => submitting.value || Boolean(latestAnalysis.value && isSkillAnalysisRunning(latestAnalysis.value)))
  const analysisError = ref('')
  let requestVersion = 0

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

  const analysisParams = () => {
    const params: { workspace_id?: string, ref_kind: SkillAnalysisRefKind, version_id?: string } = {
      ref_kind: defaultAnalysisRefKind.value,
    }
    if (selectedWorkspaceId.value) params.workspace_id = selectedWorkspaceId.value
    if (targetAnalysisVersionId.value) params.version_id = targetAnalysisVersionId.value
    return params
  }

  const applyAnalysis = (payload: SkillAnalysis | null) => {
    analysisId.value = payload?.id || ''
    if (payload) store.ingest(payload, isSkillAnalysisRunning(payload))
  }

  const loadLatestAnalysis = async () => {
    if (!skillId.value) return
    const version = ++requestVersion
    analysisLoading.value = true
    analysisError.value = ''
    try {
      const res = await api.get(`/skills/${skillId.value}/analyses/latest`, {
        params: analysisParams(),
      })
      if (version === requestVersion) applyAnalysis(res.data || null)
    } catch (error) {
      if (version !== requestVersion) return
      analysisError.value = formatApiError(error, t('skills.editor.analysis_load_failed'), t)
      actionError.value = analysisError.value
    } finally {
      if (version === requestVersion) analysisLoading.value = false
    }
  }

  const refreshAnalysisById = async (analysisId: string) => {
    if (!skillId.value || !analysisId) return null
    const version = ++requestVersion
    const res = await api.get(`/skills/${skillId.value}/analyses/${analysisId}`, {
      params: analysisParams(),
    })
    const payload = (res.data || null) as SkillAnalysis | null
    if (version === requestVersion) applyAnalysis(payload)
    return payload
  }

  const runAnalysis = async (refKind?: SkillAnalysisRefKind) => {
    if (!skillId.value || analysisRunning.value) return
    const version = ++requestVersion
    const resolvedRefKind = refKind || defaultAnalysisRefKind.value
    submitting.value = true
    analysisLoading.value = false
    analysisError.value = ''
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
      // Keep the accepted background job even if navigation changed the editor.
      if (payload) {
        store.ingest(payload, true)
        background.expand()
      }
      if (version === requestVersion) applyAnalysis(payload)
    } catch (error) {
      if (version !== requestVersion) return
      analysisError.value = formatApiError(error, t('skills.editor.analysis_start_failed'), t)
      actionError.value = analysisError.value
    } finally {
      if (version === requestVersion) submitting.value = false
    }
  }

  const resetAnalysis = () => {
    requestVersion += 1
    analysisId.value = ''
    analysisLoading.value = false
    submitting.value = false
    analysisError.value = ''
  }

  watch(() => [skillId.value, selectedWorkspaceId.value, targetAnalysisVersionId.value], resetAnalysis, { flush: 'sync' })
  onBeforeUnmount(resetAnalysis)

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
