import api from '@/utils/api'

export interface RequirementDocumentSummary {
  id: string
  link_id: string
  name: string
  task_id: string | null
}

export function requirementDocumentsUrl(workspaceId: string, requirementId: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}/workspace-assets/requirements/${encodeURIComponent(requirementId)}/documents`
}

export function requirementDocumentUrl(workspaceId: string, documentId: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}/workspace-assets/requirement-documents/${encodeURIComponent(documentId)}`
}

export async function uploadRequirementDocument(workspaceId: string, requirementId: string, file: File) {
  const content = new FormData()
  content.append('file', file)
  const { data } = await api.post<{ id: string; name: string }>(requirementDocumentsUrl(workspaceId, requirementId), content)
  return data
}
