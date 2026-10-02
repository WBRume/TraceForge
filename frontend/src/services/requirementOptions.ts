import api from '@/utils/api'
import type { RequirementOption } from '@/types/taskRail'

export async function fetchRequirementOptions(workspaceId: string, params: {
  q?: string; ids?: string; page?: number; page_size?: number; scope?: 'all' | 'roots' | 'children'; parent_id?: string
} = {}, signal?: AbortSignal): Promise<{ items: RequirementOption[]; total: number }> {
  const { data } = await api.get(`/workspaces/${workspaceId}/workspace-assets/requirement-options`, { params, signal })
  return data
}
