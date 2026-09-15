/**
 * OAuth 三方登录 —— 前端类型定义（T04）
 * 契约来源：docs/design-oauth-login.md §2.3（接口契约固化，勿随意改动字段名）
 */

/** ticket 状态（后端 oauth_tickets.status，§2.1.3 / §2.3.2 接口 4） */
export type OAuthTicketStatus =
  | 'LOGIN_OK'
  | 'BIND_REQUIRED'
  | 'REGISTER_REQUIRED'
  | 'CONFIRM_REQUIRED'
  | 'ALREADY_BOUND'
  | 'BIND_CONFLICT'

/** 授权意图：login = 登录/注册；bind = 已登录加绑 */
export type OAuthIntent = 'login' | 'bind'

/** 客户端类型：web 浏览器 302 回调 / desktop Electron 本地回环（T05 适配） */
export type OAuthClientType = 'web' | 'desktop'

/** 接口 1：GET /auth/oauth/providers 返回的 provider 条目 */
export type OAuthProviderInfo = {
  name: string
  display_name: string
  authorize_path: string
  icon_key: string
}

export type OAuthProvidersResponse = {
  providers: OAuthProviderInfo[]
}

/** 接口 2：GET /auth/oauth/{provider}/authorize 响应 */
export type OAuthAuthorizeResponse = {
  authorize_url: string
  state: string
  expires_in: number
}

export type OAuthAuthorizeParams = {
  intent?: OAuthIntent
  client_type?: OAuthClientType
  /** 授权完成后前端应落地的站内相对路径（后端校验，禁止绝对 URL） */
  redirect_after?: string
}

/** TokenResponse（路径 A / B / C 成功后签发） */
export type OAuthTokenResponse = {
  access_token: string
  refresh_token: string
  token_type: string
}

/** 接口 4：POST /auth/oauth/resolve 响应（幂等读，不消费 ticket） */
export type OAuthResolveResult = {
  status: OAuthTicketStatus
  provider?: string
} & Partial<OAuthTokenResponse> & {
    /** status=BIND_REQUIRED：🔴 脱敏邮箱（如 z***@example.com），未认证端点不会返回完整邮箱 */
    email_masked?: string
    email_verified?: boolean
    /** status=REGISTER_REQUIRED：三方 email 仅作预填默认值，以用户手填为准（拍板 #6） */
    suggested_email?: string
    suggested_display_name?: string
    suggested_avatar_url?: string
    /** status=CONFIRM_REQUIRED：管理员账号加绑需二次密码确认 */
    reason?: string
    provider_display_name?: string
    /** status=ALREADY_BOUND */
    bound_at?: string
  }

/** 接口 5：POST /auth/oauth/bind 响应（已登录加绑终态） */
export type OAuthBindResult = {
  status: 'BOUND' | 'ALREADY_BOUND'
  identity?: OAuthIdentity
}

/** 接口 8：GET /auth/oauth/identities 返回的单条绑定身份 */
export type OAuthIdentity = {
  id: string
  provider: string
  provider_display_name: string
  provider_email: string
  provider_avatar_url: string
  created_at: string
  last_login_at: string
}

export type OAuthIdentitiesResponse = {
  identities: OAuthIdentity[]
  available_providers: string[]
}

/** 接口 6/7 终态成功响应：绑定/注册完成并签发 token */
export type OAuthCompleteResponse = {
  status: 'BOUND' | 'REGISTERED'
  access_token: string
  refresh_token: string
  token_type: string
}

/** 后端 OAuthAPIError 统一错误体（§4.5）：{ detail, code } */
export type OAuthErrorBody = {
  detail?: string
  code?: string
  /** OAUTH_TICKET_LOCKED（423）时的冷却秒数 */
  retry_after?: number
  /** OAUTH_PASSWORD_INVALID（401）时后端可附带的剩余尝试次数（E-18） */
  attempts_left?: number
}
