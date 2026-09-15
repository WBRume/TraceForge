/**
 * OAuth 三方登录 —— 9 端点 API 封装（T04 / F-02）
 *
 * 契约来源：docs/design-oauth-login.md §2.3。
 * 约束（§4.8-5）：统一复用 src/utils/api.ts 的 axios 实例，本模块不得新建实例。
 *
 * dev mock：设置环境变量 VITE_OAUTH_MOCK=1 启用（后端 T02 未就绪时可独立跑通三页面）。
 * mock ticket 一览（直接访问 /oauth/callback?ticket=<mock ticket> 即可）：
 *   mock-login      → LOGIN_OK（路径 A 直接登录）
 *   mock-bind       → BIND_REQUIRED（路径 B 确认绑定）
 *   mock-register   → REGISTER_REQUIRED（路径 C 补全注册）
 *   mock-confirm    → CONFIRM_REQUIRED（管理员加绑二次确认）
 *   mock-already    → ALREADY_BOUND（加绑幂等）
 *   mock-conflict   → BIND_CONFLICT（加绑冲突）
 */
import api from '@/utils/api'
import type {
  OAuthAuthorizeParams,
  OAuthAuthorizeResponse,
  OAuthBindResult,
  OAuthCompleteResponse,
  OAuthErrorBody,
  OAuthIdentitiesResponse,
  OAuthProvidersResponse,
  OAuthResolveResult,
} from '@/types/oauth'

const BASE = '/auth/oauth'

export const isOAuthMockEnabled = (): boolean =>
  String(import.meta.env.VITE_OAUTH_MOCK ?? '').trim() === '1'

/* ------------------------------------------------------------------ */
/* mock 实现                                                           */
/* ------------------------------------------------------------------ */

const MOCK_PROVIDERS: OAuthProvidersResponse = {
  providers: [
    {
      name: 'github',
      display_name: 'GitHub',
      authorize_path: `${BASE}/github/authorize`,
      icon_key: 'github',
    },
  ],
}

const MOCK_TICKET_STATUS: Record<string, OAuthResolveResult> = {
  'mock-login': {
    status: 'LOGIN_OK',
    provider: 'github',
    access_token: 'mock-access-token',
    refresh_token: 'mock-refresh-token',
    token_type: 'bearer',
  },
  'mock-bind': {
    status: 'BIND_REQUIRED',
    provider: 'github',
    email_masked: 'z***@example.com',
    email_verified: false,
  },
  'mock-register': {
    status: 'REGISTER_REQUIRED',
    provider: 'github',
    suggested_email: 'dev@example.com',
    suggested_display_name: 'Octocat',
    suggested_avatar_url: '',
    email_verified: true,
  },
  'mock-confirm': {
    status: 'CONFIRM_REQUIRED',
    provider: 'github',
    reason: 'admin_bind',
    provider_display_name: 'Octocat',
  },
  'mock-already': {
    status: 'ALREADY_BOUND',
    provider: 'github',
    bound_at: new Date().toISOString(),
  },
  'mock-conflict': {
    status: 'BIND_CONFLICT',
    provider: 'github',
  },
}

const delay = (ms = 300) => new Promise<void>(resolve => setTimeout(resolve, ms))

const mockAuthorizeUrl = (ticket: string): string => {
  // 指向前端自己的回调页，便于无后端时走通整个状态机
  return `${window.location.origin}/oauth/callback?ticket=${ticket}&client_type=web`
}

const mockError = (status: number, body: OAuthErrorBody): never => {
  const error = new Error(body.detail ?? 'mock error') as Error & {
    response?: { status: number; data: OAuthErrorBody }
  }
  error.response = { status, data: body }
  throw error
}

/* ------------------------------------------------------------------ */
/* 接口封装                                                            */
/* ------------------------------------------------------------------ */

/** 接口 1：已启用 provider 列表（空列表时前端隐藏整个三方按钮区） */
export const listOAuthProviders = async (): Promise<OAuthProvidersResponse> => {
  if (isOAuthMockEnabled()) {
    await delay(150)
    return MOCK_PROVIDERS
  }
  const res = await api.get<OAuthProvidersResponse>(`${BASE}/providers`)
  return res.data
}

/** 接口 2：发起授权，返回三方授权 URL（intent=bind 时需携带 JWT，由拦截器自动附加） */
export const getOAuthAuthorizeUrl = async (
  provider: string,
  params: OAuthAuthorizeParams = {},
): Promise<OAuthAuthorizeResponse> => {
  if (isOAuthMockEnabled()) {
    await delay(150)
    return {
      authorize_url: mockAuthorizeUrl(params.intent === 'bind' ? 'mock-already' : 'mock-login'),
      state: 'mock-state',
      expires_in: 600,
    }
  }
  const res = await api.get<OAuthAuthorizeResponse>(`${BASE}/${provider}/authorize`, {
    params: {
      intent: params.intent ?? 'login',
      client_type: params.client_type ?? 'web',
      ...(params.redirect_after ? { redirect_after: params.redirect_after } : {}),
    },
  })
  return res.data
}

/** 接口 4：解析 ticket（幂等读，不消费；可重复调用） */
export const resolveOAuthTicket = async (ticket: string): Promise<OAuthResolveResult> => {
  if (isOAuthMockEnabled()) {
    await delay(300)
    const result = MOCK_TICKET_STATUS[ticket]
    if (!result) {
      mockError(410, { code: 'OAUTH_TICKET_EXPIRED', detail: 'ticket expired (mock)' })
    }
    return result
  }
  const res = await api.post<OAuthResolveResult>(`${BASE}/resolve`, { ticket })
  return res.data
}

/** 接口 5：加绑终态（已登录态；管理员账号必须传 password） */
export const bindOAuthIdentity = async (
  ticket: string,
  password?: string,
): Promise<OAuthBindResult> => {
  if (isOAuthMockEnabled()) {
    await delay(400)
    if (ticket === 'mock-conflict') {
      mockError(409, { code: 'OAUTH_IDENTITY_CONFLICT' })
    }
    return { status: 'BOUND' }
  }
  const res = await api.post<OAuthBindResult>(`${BASE}/bind`, { ticket, password })
  return res.data
}

/** 接口 6：路径 B 确认绑定（🔴 密码错误与账号不存在返回同一响应，AC-S7） */
export const confirmOAuthBind = async (
  ticket: string,
  password: string,
): Promise<OAuthCompleteResponse> => {
  if (isOAuthMockEnabled()) {
    await delay(400)
    if (password === 'wrong') {
      mockError(401, { code: 'OAUTH_PASSWORD_INVALID', attempts_left: 3 })
    }
    return {
      status: 'BOUND',
      access_token: 'mock-access-token',
      refresh_token: 'mock-refresh-token',
      token_type: 'bearer',
    }
  }
  const res = await api.post<OAuthCompleteResponse>(`${BASE}/bind/confirm`, { ticket, password })
  return res.data
}

/** 接口 7：路径 C 补全注册（email 以用户手填为准，拍板 #6） */
export const completeOAuthRegister = async (payload: {
  ticket: string
  email: string
  password: string
  display_name: string
}): Promise<OAuthCompleteResponse> => {
  if (isOAuthMockEnabled()) {
    await delay(400)
    if (payload.email.toLowerCase() === 'taken@example.com') {
      mockError(409, { code: 'OAUTH_EMAIL_TAKEN' })
    }
    return {
      status: 'REGISTERED',
      access_token: 'mock-access-token',
      refresh_token: 'mock-refresh-token',
      token_type: 'bearer',
    }
  }
  const res = await api.post<OAuthCompleteResponse>(`${BASE}/register`, payload)
  return res.data
}

/** 接口 8：当前用户已绑定身份列表（T05 设置页使用，此处一并提供） */
export const listOAuthIdentities = async (): Promise<OAuthIdentitiesResponse> => {
  if (isOAuthMockEnabled()) {
    await delay(200)
    return { identities: [], available_providers: ['github'] }
  }
  const res = await api.get<OAuthIdentitiesResponse>(`${BASE}/identities`)
  return res.data
}

/** 接口 9：解绑指定身份（T05 设置页使用） */
export const unbindOAuthIdentity = async (identityId: string): Promise<void> => {
  if (isOAuthMockEnabled()) {
    await delay(300)
    return
  }
  await api.delete(`${BASE}/identities/${identityId}`)
}
