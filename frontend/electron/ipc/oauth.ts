/**
 * Electron 桌面端 OAuth IPC（T05 / F-06，RFC 8252 本地回环方案）
 *
 * 流程：
 *   1. 渲染进程经 preload 调 sdd:oauth:start { provider, intent, clientType }
 *   2. 主进程在 127.0.0.1:{固定端口} 起一个临时 HTTP 服务监听 GET /callback
 *   3. 主进程读桌面配置（serverUrl + JWT）请求后端
 *      GET {serverUrl}/api/auth/oauth/{provider}/authorize?client_type=desktop&intent=...&loopback_port={port}
 *      拿到三方授权 URL
 *   4. 用 shell.openExternal 在【系统默认浏览器】打开授权页（绝不内嵌 webview）
 *   5. 用户在浏览器完成授权 → GitHub 回调到回环地址 http://127.0.0.1:{port}/callback?code=...&state=...
 *   6. 临时服务收到 code → 转发后端 /api/auth/oauth/{provider}/callback 兑换（code 换 token 在服务端，
 *      主进程不持有 client_secret）→ 从后端 302 Location 取回 ?ticket=...，返回极简 HTML，并双通道回传
 *      ticket 交还渲染进程；渲染进程复用既有 /resolve + 绑定流程
 *   7. 超时或捕获后关闭临时服务，无端口泄漏
 *
 * 端口说明：GitHub 等 OAuth Provider 要求回调 URL 精确匹配，故使用【固定端口】而非随机端口，
 * 对应 backend/.env 的 OAUTH_GITHUB_REDIRECT_URI_DESKTOP（host=127.0.0.1, path=/callback）。
 * 可通过环境变量 SDD_OAUTH_LOOPBACK_PORT 覆盖（修改后须同步更新 GitHub OAuth App 回调地址）。
 */
import { ipcMain, shell, BrowserWindow } from 'electron'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { URL } from 'node:url'
import { readConfig, type DesktopConfig } from './config'
import type { DesktopOAuthStartPayload, DesktopOAuthStartResult } from '../../src/types/sddDesktop'

const LOOPBACK_HOST = '127.0.0.1'
const DEFAULT_LOOPBACK_PORT = 18790
/** 用户未完成授权时的兜底超时：5 分钟 */
const OAUTH_TIMEOUT_MS = 5 * 60 * 1000

const resolveLoopbackPort = (): number => {
  const fromEnv = Number(process.env.SDD_OAUTH_LOOPBACK_PORT)
  return Number.isInteger(fromEnv) && fromEnv > 0 && fromEnv <= 65535 ? fromEnv : DEFAULT_LOOPBACK_PORT
}

const buildAuthorizeUrl = (serverUrl: string, provider: string, intent: string, port: number): string => {
  const base = serverUrl.replace(/\/+$/, '')
  const params = new URLSearchParams({
    client_type: 'desktop',
    intent,
    loopback_port: String(port),
  })
  return `${base}/api/auth/oauth/${encodeURIComponent(provider)}/authorize?${params.toString()}`
}

type LoopbackOutcome = DesktopOAuthStartResult

const startLoopbackServer = (
  port: number,
  provider: string,
  serverUrl: string,
): Promise<{ server: Server; outcome: Promise<LoopbackOutcome> }> => {
  const server = createServer()
  const outcome = new Promise<LoopbackOutcome>((resolve) => {
    let settled = false
    const finish = (value: LoopbackOutcome): void => {
      if (settled) return
      settled = true
      resolve(value)
    }

    // GitHub 回传 code → 后端 /callback 兑换 ticket（code 换 token 在服务端完成，
    // 主进程不持有 client_secret）→ 后端以 302 把浏览器重定向到 loopback?ticket=...，
    // 这里用 redirect:manual 读取 Location 取出 ticket，避免真的触发第二次浏览器跳转。
    const exchangeCodeForTicket = async (code: string, state: string): Promise<LoopbackOutcome> => {
      const base = serverUrl.replace(/\/+$/, '')
      const params = new URLSearchParams({ code, state })
      const cbUrl = `${base}/api/auth/oauth/${encodeURIComponent(provider)}/callback?${params.toString()}`
      try {
        const resp = await fetch(cbUrl, { redirect: 'manual' })
        const location = resp.headers.get('location')
        if (!location) return { error: 'oauth_no_ticket_location' }
        const locUrl = new URL(location, `http://${LOOPBACK_HOST}:${port}`)
        return {
          ticket: locUrl.searchParams.get('ticket') ?? undefined,
          status: locUrl.searchParams.get('status') ?? undefined,
          error: locUrl.searchParams.get('error') ?? undefined,
        }
      } catch (err) {
        return { error: `oauth_exchange_failed:${String(err)}` }
      }
    }

    server.on('request', (req: IncomingMessage, res: ServerResponse) => {
      const reqUrl = req.url ? new URL(req.url, `http://${LOOPBACK_HOST}:${port}`) : null
      const code = reqUrl?.searchParams.get('code') ?? undefined
      const state = reqUrl?.searchParams.get('state') ?? undefined
      const ticket = reqUrl?.searchParams.get('ticket') ?? undefined
      const status = reqUrl?.searchParams.get('status') ?? undefined
      const error = reqUrl?.searchParams.get('error') ?? undefined

      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
          '<meta name="viewport" content="width=device-width, initial-scale=1"></head>' +
          '<body style="margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;' +
          'display:flex;min-height:100vh;align-items:center;justify-content:center;background:#f8fafc;color:#0f172a">' +
          '<div style="text-align:center;padding:24px">' +
          '<div style="font-size:48px;line-height:1">✅</div>' +
          '<h2 style="margin:16px 0 8px">Authentication complete</h2>' +
          '<p style="margin:0;color:#64748b">You can close this tab and return to the app.</p>' +
          '</div></body></html>',
      )

      if (ticket || error) {
        finish({ ticket, status, error })
        return
      }
      if (code && state) {
        void exchangeCodeForTicket(code, state).then(finish)
      }
    })
  })

  return new Promise((resolve, reject) => {
    server.once('error', (err) => reject(err))
    server.listen(port, LOOPBACK_HOST, () => resolve({ server, outcome }))
  })
}

export const registerOauthIpc = (): void => {
  ipcMain.handle(
    'sdd:oauth:start',
    async (_event, payload: DesktopOAuthStartPayload): Promise<DesktopOAuthStartResult> => {
      const provider = String(payload?.provider ?? '').trim()
      const intent = payload?.intent === 'bind' ? 'bind' : 'login'
      if (!provider) {
        throw new Error('oauth start: provider is required')
      }

      const config: DesktopConfig = await readConfig()
      const serverUrl = (config.serverUrl || 'http://localhost:8000').replace(/\/+$/, '')
      const token = config.token || ''

      const port = resolveLoopbackPort()

      let server: Server
      let ticketOutcome: Promise<LoopbackOutcome>
      try {
        const started = await startLoopbackServer(port, provider, serverUrl)
        server = started.server
        ticketOutcome = started.outcome
      } catch (err) {
        throw new Error(
          `oauth start: cannot bind loopback port ${port} (${String(err)}). ` +
            'Free the port or set SDD_OAUTH_LOOPBACK_PORT to a free port and update the GitHub OAuth App callback URL.',
        )
      }

      // 向后端请求三方授权 URL（intent=bind 需携带 JWT）
      const authorizeUrl = buildAuthorizeUrl(serverUrl, provider, intent, port)
      let authorizeResponse: { authorize_url?: string }
      try {
        const headers: Record<string, string> = { Accept: 'application/json' }
        if (token) headers['Authorization'] = `Bearer ${token}`
        const resp = await fetch(authorizeUrl, { headers })
        authorizeResponse = (await resp.json()) as { authorize_url?: string }
      } catch (err) {
        server.close()
        throw new Error(`oauth start: failed to fetch authorize URL from backend (${String(err)})`)
      }

      const targetUrl = authorizeResponse.authorize_url
      if (!targetUrl) {
        server.close()
        throw new Error('oauth start: backend returned an empty authorize_url')
      }

      // RFC 8252：用系统默认浏览器打开授权页（绝不内嵌 webview）
      await shell.openExternal(targetUrl)

      const timeout = new Promise<LoopbackOutcome>((resolveTimeout) => {
        const timer = setTimeout(() => resolveTimeout({ error: 'oauth_timeout' }), OAUTH_TIMEOUT_MS)
        // 不阻止 Electron 事件循环退出
        if (typeof timer.unref === 'function') timer.unref()
      })

      const outcome = await Promise.race([ticketOutcome, timeout])

      // 双通道回传：primary 走 invoke 返回值；secondary 走 webContents.send（渲染进程可订阅）
      const win = BrowserWindow.getAllWindows()[0]
      if (win && !win.isDestroyed()) {
        win.webContents.send('sdd:oauth:ticket', outcome)
      }

      server.close()
      return { ticket: outcome.ticket, status: outcome.status, error: outcome.error }
    },
  )
}
