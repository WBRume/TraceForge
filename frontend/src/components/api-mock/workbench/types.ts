import type { ApiMockJob } from '@/types/apiMock'

export type TaskOption = {
  id: string
  name: string
}

export type WorkspaceMemberProfile = {
  user_id: string
  display_name: string
  email: string
  avatar_svg?: string | null
  avatar_url?: string | null
}

export type OnlinePresenceUser = {
  id: string
  displayName: string
  email?: string | null
  avatarSvg?: string | null
  avatarUrl?: string | null
}

export type PermissionFlags = {
  view_api_mock?: boolean
  manage_api_mock?: boolean
  publish_api_mock?: boolean
}

export type ActiveJobState = Pick<ApiMockJob, 'id' | 'job_type' | 'status' | 'progress' | 'message' | 'result_json'>

export type ApiMockLockedDetail = {
  code?: unknown
  message?: unknown
  meta?: unknown
}

export type ApiMockErrorBody = {
  detail?: ApiMockLockedDetail | string
}

export type ApiMockJobListResponse = {
  items?: ApiMockJob[]
  total?: number
}
