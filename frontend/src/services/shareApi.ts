/**
 * 任务会话分享公开 API 客户端。
 *
 * 独立 axios 实例：公开页凭证错误不能交给全局 401「强制登出」拦截器
 * （访客本就未登录）。凭证经专用头 X-Share-Access 携带，与登录认证分离。
 */
import axios from 'axios'
import { DEFAULT_SERVER_URL, buildApiBaseUrl } from '@/utils/api'

export type ShareViewMode = 'NORMAL_REDIRECT' | 'READ_ONLY' | 'INPUT_ONLY'

export type ShareExchangeResponse = {
  view_mode: ShareViewMode
  access_token: string
  access_expires_at: string
  visitor_id: string
  /** 公开实时通道 /ws/public/session-shares/{share_id} 使用 */
  share_id: string
  task_name: string | null
  instruction_text: string | null
  expires_at: string
  redirect_path: string | null
}

export type ShareResolveResponse = {
  view_mode: ShareViewMode
  task_name: string | null
  instruction_text: string | null
  expires_at: string
  redirect_path: string | null
}

export type SharedHistoryMessage = {
  message_id: string
  role: string
  content: string
  safe_message_type: string
  created_at: string
  safe_card_summary: string | null
}

export type SharedHistoryResponse = {
  messages: SharedHistoryMessage[]
  has_more: boolean
  next_cursor: string | null
}

export type ShareSuggestionReceipt = {
  submission_id: string
  client_submission_id: string
  created_at: string
  status: string
}

export class ShareApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

const resolveBase = (): string => {
  const stored = typeof localStorage !== 'undefined'
    ? localStorage.getItem('sdd_server_url')
    : null
  return buildApiBaseUrl(stored || DEFAULT_SERVER_URL)
}

const shareApi = axios.create({
  baseURL: resolveBase(),
  timeout: 15000,
})

// 访客可能也带着登录态：exchange/resolve 会用到，但绝不能因 401 登出
shareApi.interceptors.request.use((config) => {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('sdd_token') : null
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const accessToken = sessionStorage.getItem('sdd.share.access_token')
  if (accessToken) {
    config.headers['X-Share-Access'] = accessToken
  }
  return config
})

const toShareError = (error: unknown): ShareApiError => {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const status = Number(response?.status || 0)
  const detail = response?.data?.detail
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const payload = detail as { code?: string; message?: string }
    return new ShareApiError(status, String(payload.code || ''), String(payload.message || '请求失败'))
  }
  if (typeof detail === 'string' && detail) {
    return new ShareApiError(status, '', detail)
  }
  return new ShareApiError(status, '', '网络异常，请稍后重试')
}

export const setShareAccessToken = (token: string | null) => {
  if (token) {
    sessionStorage.setItem('sdd.share.access_token', token)
  } else {
    sessionStorage.removeItem('sdd.share.access_token')
  }
}

export const getShareAccessToken = (): string | null =>
  sessionStorage.getItem('sdd.share.access_token')

/** 公开实时通道使用的分享 id（仅当前标签页）。 */
export const setShareId = (shareId: string | null) => {
  if (shareId) {
    sessionStorage.setItem('sdd.share.share_id', shareId)
  } else {
    sessionStorage.removeItem('sdd.share.share_id')
  }
}

export const getShareId = (): string | null =>
  sessionStorage.getItem('sdd.share.share_id')

/** 保留原始令牌（仅当前标签页），凭证过期后重新 exchange。 */
export const setShareToken = (token: string) => {
  sessionStorage.setItem('sdd.share.token', token)
}

export const getShareToken = (): string | null =>
  sessionStorage.getItem('sdd.share.token')

export const clearShareSession = () => {
  sessionStorage.removeItem('sdd.share.token')
  sessionStorage.removeItem('sdd.share.access_token')
  sessionStorage.removeItem('sdd.share.share_id')
}

export const shareExchange = async (token: string): Promise<ShareExchangeResponse> => {
  try {
    const res = await shareApi.post<ShareExchangeResponse>('/public/session-shares/exchange', { token })
    return res.data
  } catch (error) {
    throw toShareError(error)
  }
}

export const shareResolve = async (): Promise<ShareResolveResponse> => {
  try {
    const res = await shareApi.post<ShareResolveResponse>('/public/session-shares/resolve')
    return res.data
  } catch (error) {
    throw toShareError(error)
  }
}

export const fetchSharedHistory = async (cursor?: string | null, pageSize = 50): Promise<SharedHistoryResponse> => {
  try {
    const params: Record<string, unknown> = { page_size: pageSize }
    if (cursor) params.cursor = cursor
    const res = await shareApi.get<SharedHistoryResponse>('/public/session-shares/history', { params })
    return res.data
  } catch (error) {
    throw toShareError(error)
  }
}

export const submitShareSuggestion = async (payload: {
  content: string
  display_name?: string | null
  client_submission_id: string
}): Promise<ShareSuggestionReceipt> => {
  try {
    const res = await shareApi.post<ShareSuggestionReceipt>('/public/session-shares/suggestions', payload)
    return res.data
  } catch (error) {
    throw toShareError(error)
  }
}
