import { shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { RequirementDetail, RequirementSummary } from '@/types/workspaceAssets'

export function useRequirementWork(workspace: () => string, userId: () => string | undefined,
  prepare: (requirement: RequirementSummary) => void, refresh: () => void | Promise<unknown>) {
  const router = useRouter()
  const { t } = useI18n()
  const busy = shallowRef<string | null>(null)

  function enter(requirement: RequirementSummary) {
    const candidates = (requirement.linked_tasks || []).filter(task => task.relation_type === 'COVERS'
      && !['COMPLETED', 'FAILED'].includes(task.task_status))
    const existing = candidates.find(task => task.creator_id === userId()) ?? candidates[0]
    if (existing) {
      void router.push({ name: 'taskChat', params: { wsId: workspace(), taskId: existing.task_id } })
    } else {
      prepare(requirement)
    }
  }

  async function claim(requirement: RequirementSummary, clarify: boolean) {
    if (busy.value) return
    const wsId = workspace()
    busy.value = requirement.id
    try {
      const { data } = await api.post<RequirementDetail>(
        `/workspaces/${wsId}/workspace-assets/requirements/${requirement.id}/claim`, null, { params: { clarify } },
      )
      if (wsId !== workspace()) return
      ElMessage.success(t('workspace_assets.delivery.claimed'))
      await refresh()
      if (clarify && wsId === workspace()) enter(data.requirement)
    } catch (error) {
      ElMessage.error(formatApiError(error, t('workspace_assets.requirements.task_links.save_failed'), t))
      if (wsId === workspace()) await refresh()
    } finally {
      busy.value = null
    }
  }

  return { busy, claim }
}
