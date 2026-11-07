import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import api from '@/utils/api'
import { domainMilestones } from '@/utils/domainMilestones'
import type { SkillAnalysis } from '@/types/skillAnalysis'
import type { ProvisionJobView } from '@/stores/provisioning'

export const isSkillAnalysisRunning = (analysis: SkillAnalysis) =>
  analysis.status === 'PENDING' || analysis.status === 'RUNNING'

export const useSkillAnalysisStore = defineStore('skillAnalysis', () => {
  const analyses = ref<Record<string, SkillAnalysis>>({})
  const tracked = ref<string[]>([])
  const dismissed = new Set<string>()
  let generation = 0
  let refreshPromise: Promise<void> | null = null

  const ingest = (payload: SkillAnalysis, track = false) => {
    if (!payload?.id || !payload.skill_id || !payload.workspace_id) return null
    const previous = analyses.value[payload.id]
    // POST/GET responses can arrive after a newer notification for the same run.
    const stale = previous && (
      (!isSkillAnalysisRunning(previous) && isSkillAnalysisRunning(payload))
      || (isSkillAnalysisRunning(previous) && isSkillAnalysisRunning(payload)
        && (previous.progress > payload.progress
          || (previous.progress === payload.progress
            && domainMilestones(previous.file_stats.domain_milestones).length > domainMilestones(payload.file_stats.domain_milestones).length)))
    )
    const current = stale ? previous : payload
    analyses.value = { ...analyses.value, [payload.id]: current }
    if (track && !dismissed.has(payload.id) && !tracked.value.includes(payload.id)) {
      tracked.value = [...tracked.value, payload.id]
    }
    return current
  }

  const jobs = computed<ProvisionJobView[]>(() => tracked.value.flatMap(id => {
    const analysis = analyses.value[id]
    if (!analysis) return []
    const terminal = !isSkillAnalysisRunning(analysis)
    return [{
      jobId: id, kind: 'skill_analysis', taskId: '', workspaceId: analysis.workspace_id,
      taskName: analysis.skill_name ? `技能审阅：${analysis.skill_name}` : '技能包审阅',
      status: analysis.status, stage: '', progress: analysis.progress,
      message: analysis.message || '', errorMessage: analysis.error_message || '',
      cancelRequested: false, ready: false, terminal,
      requirementId: '', requirementTitle: '', batch: null, viewed: false, handedOver: true,
      domain_milestones: terminal ? [] : domainMilestones(analysis.file_stats.domain_milestones),
      analysis,
    }]
  }))

  const dismiss = (id: string) => {
    dismissed.add(id)
    tracked.value = tracked.value.filter(value => value !== id)
  }

  // Only connection/recovery events call this; there is no timer or polling fallback.
  const refresh = () => {
    if (refreshPromise) return refreshPromise
    const currentGeneration = generation
    const known = tracked.value.map(id => analyses.value[id]).filter(isSkillAnalysisRunning)
    const refreshSnapshot = async () => {
      await Promise.allSettled([
        (async () => {
          const { data } = await api.get<SkillAnalysis[]>('/skills/analyses/active')
          if (currentGeneration !== generation) return
          for (const analysis of data) ingest(analysis, true)
        })(),
        ...known.map(async previous => {
          const { data } = await api.get<SkillAnalysis>(`/skills/${previous.skill_id}/analyses/${previous.id}`, {
            params: { workspace_id: previous.workspace_id },
          })
          if (currentGeneration === generation && analyses.value[previous.id] === previous) ingest(data)
        }),
      ])
    }
    const promise = refreshSnapshot().finally(() => {
      if (refreshPromise === promise) refreshPromise = null
    })
    refreshPromise = promise
    return promise
  }

  const reset = () => {
    generation += 1
    refreshPromise = null
    analyses.value = {}
    tracked.value = []
    dismissed.clear()
  }

  return { analyses, jobs, ingest, dismiss, refresh, reset }
})
