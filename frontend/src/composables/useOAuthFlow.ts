/**
 * OAuth 流程编排组合式函数（T04 / F-04）
 * §3.8.2：useOAuthFlow 是「唯一感知双端差异的地方」。
 *  - Web：调 authorize 接口拿到 authorize_url 后整页跳转；
 *  - Electron：预留 sddDesktop.oauth.start() 通道（T05 实现 IPC 后无缝切换），
 *    未暴露前回退 Web 行为，页面逻辑不写死 Web-only。
 */
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import { useOAuthStore } from '@/stores/oauth'
import {
  bindOAuthIdentity,
  getOAuthAuthorizeUrl,
  resolveOAuthTicket,
} from '@/services/oauthApi'
import { getSddDesktop, isElectron } from '@/utils/runtime'
import type {
  OAuthClientType,
  OAuthIntent,
  OAuthResolveResult,
} from '@/types/oauth'

/** 站内相对路径校验（防开放重定向，与后端 redirect_after 校验一致） */
export const sanitizeInternalPath = (path: string | null | undefined): string | null => {
  if (!path) return null
  if (!path.startsWith('/')) return null
  if (path.startsWith('//')) return null
  return path
}

export type StartAuthorizeOptions = {
  intent?: OAuthIntent
  /** 授权完成后落地的站内路由（仅 web） */
  redirectAfter?: string
  clientType?: OAuthClientType
}

export const useOAuthFlow = () => {
  const authStore = useAuthStore()
  const oauthStore = useOAuthStore()

  /**
   * 发起三方授权。
   * intent：login = 登录/注册；bind = 已登录加绑（E-14：已登录时按钮语义切为绑定）。
   *
   * 返回 resolve 结果（Electron 桌面端）或 undefined（web 端会整页跳走）。
   */
  const startAuthorize = async (
    provider: string,
    options: StartAuthorizeOptions = {},
  ): Promise<OAuthResolveResult | undefined> => {
    const intent: OAuthIntent = options.intent ?? 'login'
    const clientType: OAuthClientType = options.clientType ?? (isElectron() ? 'desktop' : 'web')

    // T05：Electron 走本地回环（RFC 8252），主进程打开系统浏览器并接收回调，
    // 把 ticket 回抛后由前端复用既有 /resolve + 绑定流程。
    const desktopOAuth = getSddDesktop()?.oauth
    if (isElectron() && desktopOAuth?.start) {
      const result = await desktopOAuth.start({ provider, intent, clientType })
      if (result?.error) {
        throw new Error(`oauth_desktop_error:${result.error}`)
      }
      if (result?.ticket) {
        return await resolveAndDispatch(result.ticket, options.redirectAfter)
      }
      return
    }

    const res = await getOAuthAuthorizeUrl(provider, {
      intent,
      client_type: clientType,
      redirect_after: options.redirectAfter,
    })
    // state 校验是服务端职责（C-3），前端不存 localStorage 校验
    window.location.href = res.authorize_url
  }

  /**
   * resolve ticket 并按 §3.8.1 状态机分发。
   * 返回 resolve 结果，供回调页决定后续 UI（弹密码确认框等）。
   */
  const resolveAndDispatch = async (
    ticket: string,
    fallbackRedirect?: string,
  ): Promise<OAuthResolveResult> => {
    const result = await resolveOAuthTicket(ticket)
    oauthStore.setResolveResult(result)

    switch (result.status) {
      case 'LOGIN_OK': {
        // 回调 URL 永远不含 JWT，token 只通过 resolve 兑换（C-2 / AC-S8）
        if (result.access_token) {
          authStore.setToken(result.access_token)
          await authStore.fetchCurrentUser()
          oauthStore.resetFlow()
          const target = sanitizeInternalPath(fallbackRedirect) ?? '/workspaces'
          await router.push(target)
          break
        }
        // 加绑终态（intent=bind，普通用户）：token-less LOGIN_OK → 调 /bind 完成绑定。
        // 🔴 红线：此处绝不会签发 token（resolve 对 intent=bind 的 LOGIN_OK 不含 token），
        // 仅创建身份绑定。完成后不主动跳转，由调用方（设置页 / 回调页）决定落地。
        oauthStore.pendingTicket = ticket
        try {
          await bindOAuthIdentity(ticket)
          await authStore.fetchCurrentUser()
          oauthStore.completedBindProvider = result.provider ?? ''
        } finally {
          oauthStore.pendingTicket = null
        }
        oauthStore.resetFlow()
        const target = sanitizeInternalPath(fallbackRedirect)
        if (target) {
          await router.push(target)
        }
        break
      }
      case 'BIND_REQUIRED':
        // 路径 B：跳确认绑定页（未登录态，密码验证后绑定并登录）
        await router.push({ name: 'oauthBindConfirm', query: { ticket } })
        break
      case 'REGISTER_REQUIRED':
        // 路径 C：跳补全注册页（ticket 兑换预填信息，邮箱手填优先）
        await router.push({ name: 'oauthRegister', query: { ticket } })
        break
      case 'CONFIRM_REQUIRED':
        // 管理员加绑：需二次密码确认。暂存 ticket，由调用方弹密码确认框调 /bind。
        oauthStore.pendingTicket = ticket
        break
      case 'ALREADY_BOUND':
      case 'BIND_CONFLICT':
        // 加绑相关终态：由回调页展示，不自动跳转
        break
    }
    return result
  }

  return {
    startAuthorize,
    resolveAndDispatch,
  }
}
