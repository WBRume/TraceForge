<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, Inbox, Loader2, LogIn, Send } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import {
  clearShareSession,
  fetchSharedHistory,
  getShareToken,
  setShareAccessToken,
  setShareToken,
  shareExchange,
  shareResolve,
  submitShareSuggestion,
  ShareApiError,
  type SharedHistoryMessage,
} from '@/services/shareApi'

/**
 * 独立公开分享页：不挂载 ChatView，不初始化执行面板 / 任务订阅 / 普通 WS。
 * 令牌放在 fragment（不随请求 / Referer 发送），读取后立即从地址栏移除；
 * 原始令牌与短期凭证均保存在当前标签页 sessionStorage。
 *
 * READ_ONLY：会话气泡样式（与正常会话一致的左右分列 + 元信息行），
 * 历史「加载更早」向上分页；实时更新走独立公开 WS 通道
 * （ws/public/session-shares/{share_id}，只收 share_history_changed nudge，
 * 收到后重拉最新一页），断线静默降级为手动刷新。
 * INPUT_ONLY：邀请说明 + 提交回执。NORMAL_REDIRECT 由站内路由跳正常会话。
 */
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

type PageState =
  | { kind: 'loading' }
  | { kind: 'unavailable'; reason: string }
  | { kind: 'read'; taskId: string; shareId: string; taskName: string; expiresAt: string }
  | { kind: 'input'; instruction: string | null; expiresAt: string }

const state = ref<PageState>({ kind: 'loading' })

const historyMessages = shallowRef<SharedHistoryMessage[]>([])
const historyHasMore = ref(false)
const historyCursor = ref<string | null>(null)
const historyLoading = ref(false)
const loadingMore = ref(false)
const historyStale = ref(false)
/** 最新一条已展示消息的 id：nudge 重拉时按位置增量追加 */
const lastMessageId = ref<string | null>(null)

const inputContent = ref('')
const displayName = ref('')
const submitting = ref(false)
const receipt = ref<{ created_at: string } | null>(null)
const submitError = ref('')

// 幂等键：同一未确认提交重试复用
let pendingSubmissionId: string | null = null

let shareWs: WebSocket | null = null
let wsReconnectTimer: number | null = null
let wsReconnectAttempt = 0

const readTokenFromFragment = (): string | null => {
  const hash = String(window.location.hash || '')
  const match = hash.match(/[#&]token=([^&]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

const stripFragment = () => {
  // 令牌读取后立即从地址栏移除
  window.history.replaceState(null, '', window.location.pathname)
}

const unavailable = (reason: string) => {
  // 分享不可用：清除页面会话数据与实时连接
  closeShareWs()
  clearShareSession()
  historyMessages.value = []
  state.value = { kind: 'unavailable', reason }
}

const errorText = (error: ShareApiError): string => {
  // 撤销即删除：撤销/失效的链接统一按不存在处理（响应不含资源信息）
  if (error.code === 'SHARE_EXPIRED') return t('share.unavailable_expired')
  if (error.code === 'SHARE_SESSION_INVALID') return t('share.unavailable_session_invalid')
  if (error.code === 'SHARE_CREATOR_FORBIDDEN') return t('share.unavailable_creator_forbidden')
  if (error.code === 'SHARE_NOT_FOUND' || error.code === 'SHARE_ACCESS_INVALID') {
    return t('share.unavailable_not_found')
  }
  if (error.status === 429) return t('share.unavailable_rate_limited')
  return t('share.unavailable_unknown')
}

// ── 历史分页：首屏拉最新一页，向上「加载更早」 ──

const loadHistoryPage = async (cursor?: string | null) => {
  historyLoading.value = true
  try {
    const res = await fetchSharedHistory(cursor)
    if (cursor) {
      historyMessages.value = [...res.messages, ...historyMessages.value]
    } else {
      historyMessages.value = res.messages
    }
    historyHasMore.value = res.has_more
    historyCursor.value = res.next_cursor
    lastMessageId.value = res.messages.length
      ? res.messages[res.messages.length - 1].message_id
      : null
  } catch (error) {
    if (error instanceof ShareApiError && error.code === 'SHARE_HISTORY_STALE') {
      // 撤销等历史变化：清空缓存后重新拉取，并保留提示
      historyStale.value = true
      await loadHistoryPage()
    } else {
      throw error
    }
  } finally {
    historyLoading.value = false
  }
}

const loadOlder = async () => {
  if (!historyHasMore.value || !historyCursor.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const res = await fetchSharedHistory(historyCursor.value)
    historyMessages.value = [...res.messages, ...historyMessages.value]
    historyHasMore.value = res.has_more
    historyCursor.value = res.next_cursor
  } catch (error) {
    if (error instanceof ShareApiError && error.code === 'SHARE_HISTORY_STALE') {
      historyStale.value = true
      await loadHistoryPage()
    }
  } finally {
    loadingMore.value = false
  }
}

/** WS nudge / 手动刷新：重拉最新一页，按 message_id 增量替换/追加。 */
const refreshHistory = async () => {
  if (state.value.kind !== 'read' || historyLoading.value) return
  historyStale.value = false
  try {
    const res = await fetchSharedHistory()
    if (!lastMessageId.value || !res.messages.length) {
      historyMessages.value = res.messages
    } else {
      const idx = res.messages.findIndex((m) => m.message_id === lastMessageId.value)
      if (idx >= 0) {
        const fresh = res.messages.slice(idx + 1)
        if (fresh.length) historyMessages.value = [...historyMessages.value, ...fresh]
      } else {
        // 快照里找不到锚点（历史被撤销等）：整体替换
        historyMessages.value = res.messages
        historyStale.value = true
      }
    }
    lastMessageId.value = res.messages.length
      ? res.messages[res.messages.length - 1].message_id
      : null
    historyHasMore.value = res.has_more
    historyCursor.value = res.next_cursor
  } catch (error) {
    if (error instanceof ShareApiError && error.code === 'SHARE_HISTORY_STALE') {
      historyStale.value = true
      await loadHistoryPage()
    }
  }
}

// ── 实时通道：独立公开 WS，只收 share_history_changed nudge ──

const closeShareWs = () => {
  if (wsReconnectTimer !== null) {
    window.clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }
  if (shareWs) {
    shareWs.onopen = null
    shareWs.onmessage = null
    shareWs.onerror = null
    shareWs.onclose = null
    shareWs.close()
    shareWs = null
  }
  wsReconnectAttempt = 0
}

const connectShareWs = (shareId: string) => {
  if (shareWs && shareWs.readyState === WebSocket.OPEN) return
  const { origin } = window.location
  const wsProtocol = origin.startsWith('https:') ? 'wss:' : 'ws:'
  const accessToken = sessionStorage.getItem('sdd.share.access_token') || ''
  if (!accessToken) return
  const url = `${wsProtocol}//${origin.replace(/^https?:/, '')}/ws/public/session-shares/${shareId}?access=${encodeURIComponent(accessToken)}`
  try {
    shareWs = new WebSocket(url)
  } catch {
    return
  }
  shareWs.onmessage = (event) => {
    try {
      const data = JSON.parse(String(event.data))
      if (data?.type === 'share_history_changed') {
        void refreshHistory()
      } else if (data?.type === 'resync_required') {
        // 无游标连接的握手：页面已用 REST 建立快照，直接回执进入 LIVE
        shareWs?.send(JSON.stringify({
          type: 'resync_complete',
          epoch: data.epoch,
          barrier_sequence: data.barrier_sequence,
        }))
      }
      // resync_ok / 其他控制帧：无需处理
    } catch {
      // 忽略无法解析的帧
    }
  }
  shareWs.onclose = () => {
    // 指数退避重连；页面不可见时暂停（回前台后由 visibilitychange 重连）
    if (state.value.kind !== 'read') return
    if (document.visibilityState !== 'visible') return
    if (wsReconnectTimer !== null) return
    const delay = Math.min(1000 * 2 ** wsReconnectAttempt, 15000)
    wsReconnectAttempt += 1
    wsReconnectTimer = window.setTimeout(() => {
      wsReconnectTimer = null
      if (state.value.kind === 'read') connectShareWs(shareId)
    }, delay)
  }
}

const onVisibilityChange = () => {
  if (
    document.visibilityState === 'visible'
    && state.value.kind === 'read'
    && (!shareWs || shareWs.readyState !== WebSocket.OPEN)
  ) {
    connectShareWs(state.value.shareId)
  }
}

// ── 初始化与视图分流 ──

const initFromToken = async (token: string) => {
  setShareToken(token)
  try {
    const exchanged = await shareExchange(token)
    setShareAccessToken(exchanged.access_token)

    if (exchanged.view_mode === 'NORMAL_REDIRECT' && exchanged.redirect_path) {
      // 服务端生成的站内目标（不接受任意 return_url）
      router.replace(exchanged.redirect_path)
      return
    }
    if (exchanged.view_mode === 'INPUT_ONLY') {
      state.value = {
        kind: 'input',
        instruction: exchanged.instruction_text,
        expiresAt: exchanged.expires_at,
      }
      return
    }
    state.value = {
      kind: 'read',
      taskId: '',
      shareId: exchanged.share_id,
      taskName: exchanged.task_name || '',
      expiresAt: exchanged.expires_at,
    }
    await loadHistoryPage()
    connectShareWs(exchanged.share_id)
  } catch (error) {
    if (error instanceof ShareApiError) {
      unavailable(errorText(error))
    } else {
      unavailable(t('share.unavailable_unknown'))
    }
  }
}

const revalidateAccess = async () => {
  try {
    const resolved = await shareResolve()
    if (resolved.view_mode === 'NORMAL_REDIRECT' && resolved.redirect_path) {
      router.replace(resolved.redirect_path)
      return
    }
    // 重新换取视图（凭证可能临期）
    const token = getShareToken()
    if (token) {
      const exchanged = await shareExchange(token)
      setShareAccessToken(exchanged.access_token)
    }
  } catch (error) {
    if (error instanceof ShareApiError) {
      unavailable(errorText(error))
    }
  }
}

const submitInput = async () => {
  if (state.value.kind !== 'input' || submitting.value) return
  const content = inputContent.value.trim()
  if (!content) return
  submitting.value = true
  submitError.value = ''
  try {
    if (!pendingSubmissionId) {
      pendingSubmissionId = `sub-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    }
    const result = await submitShareSuggestion({
      content,
      display_name: displayName.value.trim() || null,
      client_submission_id: pendingSubmissionId,
    })
    receipt.value = result
    pendingSubmissionId = null
    inputContent.value = ''
    displayName.value = ''
  } catch (error) {
    if (error instanceof ShareApiError) {
      if (error.status === 410) {
        unavailable(errorText(error))
      } else if (error.status === 429) {
        submitError.value = t('share.unavailable_rate_limited')
      } else if (error.code === 'SHARE_ACCESS_EXPIRED') {
        // 凭证过期：重新交换后重试
        await revalidateAccess()
        submitError.value = t('share.submit_retry_hint')
      } else {
        submitError.value = error.message || t('share.submit_failed')
      }
    } else {
      submitError.value = t('share.submit_failed')
    }
  } finally {
    submitting.value = false
  }
}

const roleLabel = (role: string): string =>
  role === 'user' ? t('share.role_user') : t('share.role_assistant')

const formatTime = (value: string): string =>
  new Date(value).toLocaleString()

const formatBubbleTime = (value: string): string => {
  const date = new Date(value)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

const expiredHint = computed(() => {
  if (state.value.kind !== 'loading' && 'expiresAt' in state.value) {
    return t('share.page_expires_hint', { date: formatTime(state.value.expiresAt) })
  }
  return ''
})

/** 未登录访客：只读页给出登录引导（非强制） */
const showLoginHint = computed(() => (
  state.value.kind === 'read' && !authStore.isAuthenticated
))

const goLogin = () => {
  router.push({ name: 'login', query: { redirect: window.location.pathname } })
}

onMounted(async () => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  const token = readTokenFromFragment() || getShareToken()
  if (token) {
    stripFragment()
    await initFromToken(token)
  } else {
    unavailable(t('share.unavailable_not_found'))
  }
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  closeShareWs()
})
</script>

<template>
  <div class="shared-session-page">
    <div class="shared-session-container">
      <!-- 加载中 -->
      <div v-if="state.kind === 'loading'" class="shared-state shared-loading">
        <Loader2 class="w-7 h-7 spin" />
        <p>{{ $t('share.page_loading') }}</p>
      </div>

      <!-- 分享不可用 -->
      <div v-else-if="state.kind === 'unavailable'" class="shared-state shared-unavailable">
        <AlertTriangle class="w-8 h-8 state-icon warn" />
        <h1>{{ $t('share.unavailable_title') }}</h1>
        <p>{{ state.reason }}</p>
        <p class="shared-brand">TraceForge</p>
      </div>

      <!-- 只读会话：与正常会话一致的气泡布局 -->
      <template v-else-if="state.kind === 'read'">
        <header class="shared-header">
          <div class="shared-header-main">
            <h1 class="shared-task-name">{{ state.taskName || $t('share.page_default_title') }}</h1>
            <span class="shared-readonly-badge">{{ $t('share.readonly_badge') }}</span>
          </div>
        </header>

        <div class="shared-notice-bar">
          <span>{{ $t('share.readonly_notice') }}<template v-if="expiredHint"> · {{ expiredHint }}</template></span>
        </div>
        <div v-if="historyStale" class="shared-stale-hint">{{ $t('share.history_stale_hint') }}</div>

        <!-- 未登录引导：登录后可直接进入正常会话 -->
        <div v-if="showLoginHint" class="shared-login-hint">
          <LogIn class="w-4 h-4" />
          <span>{{ $t('share.login_hint') }}</span>
          <button type="button" class="shared-login-btn" @click="goLogin">
            {{ $t('share.login_button') }}
          </button>
        </div>

        <main class="shared-history">
          <div v-if="historyLoading" class="shared-state shared-loading shared-history-loading">
            <Loader2 class="w-6 h-6 spin" />
          </div>
          <p v-else-if="historyMessages.length === 0" class="shared-empty">
            {{ $t('share.history_empty') }}
          </p>

          <button
            v-if="historyHasMore && !historyLoading"
            type="button"
            class="shared-load-more"
            :disabled="loadingMore"
            @click="loadOlder"
          >
            <Loader2 v-if="loadingMore" class="w-3.5 h-3.5 spin" />
            {{ $t('share.load_more') }}
          </button>

          <!-- 会话气泡（样式与正常会话消息一致） -->
          <div
            v-for="msg in historyMessages"
            :key="msg.message_id"
            class="message-wrapper"
            :class="msg.role === 'user' ? 'role-user' : 'role-assistant'"
          >
            <div class="message-stack">
              <div class="message-meta">
                <time class="message-time">{{ formatBubbleTime(msg.created_at) }}</time>
                <span class="message-author">{{ roleLabel(msg.role) }}</span>
              </div>
              <div class="message-bubble">
                <template v-if="msg.safe_message_type === 'unsupported'">
                  <p class="shared-msg-unsupported">
                    {{ msg.safe_card_summary || $t('share.unsupported_content') }}
                  </p>
                </template>
                <div v-else class="msg-content">{{ msg.content }}</div>
              </div>
            </div>
          </div>
        </main>
      </template>

      <!-- 邀请输入 -->
      <template v-else-if="state.kind === 'input'">
        <header class="shared-header">
          <div class="shared-header-main">
            <h1 class="shared-task-name">{{ $t('share.input_title') }}</h1>
          </div>
        </header>

        <p v-if="state.instruction" class="shared-instruction">{{ state.instruction }}</p>
        <p class="shared-notice">{{ $t('share.input_notice') }}<template v-if="expiredHint"> · {{ expiredHint }}</template></p>

        <main class="shared-input-area">
          <div v-if="!receipt" class="shared-input-form">
            <input
              v-model="displayName"
              type="text"
              class="shared-name-input"
              maxlength="100"
              :placeholder="$t('share.display_name_placeholder')"
            />
            <textarea
              v-model="inputContent"
              class="shared-content-input"
              rows="6"
              maxlength="20000"
              :placeholder="$t('share.content_placeholder')"
            ></textarea>
            <p v-if="submitError" class="shared-submit-error">{{ submitError }}</p>
            <button
              type="button"
              class="shared-submit-btn"
              :disabled="submitting || !inputContent.trim()"
              @click="submitInput"
            >
              <Send class="w-4 h-4" />
              {{ $t('share.submit_button') }}
            </button>
            <p class="shared-input-hint">{{ $t('share.input_hint') }}</p>
          </div>

          <div v-else class="shared-receipt">
            <div class="shared-receipt-icon">
              <Inbox class="w-7 h-7" />
            </div>
            <h2>{{ $t('share.receipt_title') }}</h2>
            <p>{{ $t('share.receipt_body') }}</p>
            <p class="shared-receipt-meta">{{ formatTime(receipt.created_at) }}</p>
          </div>
        </main>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* 容器接近全宽（与正常会话的可用宽度一致），气泡自身限宽 */
.shared-session-page {
  min-height: 100vh;
  background: #f1f5f9;
  padding: 24px 32px;
  display: flex;
  justify-content: center;
}

.shared-session-container {
  width: 100%;
  max-width: 1280px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.shared-state {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 48px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #64748b;
}

.shared-state h1 {
  margin: 0;
  font-size: 1.05rem;
  color: #0f172a;
}

.shared-state p {
  margin: 0;
  font-size: 0.85rem;
  text-align: center;
  line-height: 1.5;
}

.shared-loading .spin,
.w-7 {
  width: 28px;
  height: 28px;
}

.w-6 {
  width: 24px;
  height: 24px;
}

.w-4 {
  width: 16px;
  height: 16px;
}

.w-8 {
  width: 32px;
  height: 32px;
}

.w-3\.5 {
  width: 14px;
  height: 14px;
}

.state-icon.warn {
  color: #f59e0b;
}

.shared-brand {
  margin-top: 16px !important;
  font-size: 0.72rem !important;
  color: #cbd5e1 !important;
  letter-spacing: 0.04em;
}

.shared-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.shared-header-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.shared-task-name {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.shared-readonly-badge {
  flex-shrink: 0;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
}

.shared-notice-bar {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 14px;
  font-size: 0.74rem;
  color: #94a3b8;
  line-height: 1.5;
}

.shared-notice {
  margin: 0;
  font-size: 0.76rem;
  color: #94a3b8;
  line-height: 1.5;
}

.shared-stale-hint {
  margin: 0;
  font-size: 0.74rem;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: 8px;
  padding: 6px 10px;
}

/* ── 未登录引导 ── */
.shared-login-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 10px;
  padding: 9px 14px;
  font-size: 0.78rem;
  color: #0369a1;
}

.shared-login-hint .w-4 {
  flex-shrink: 0;
}

.shared-login-hint span {
  flex: 1;
  line-height: 1.4;
}

.shared-login-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 8px;
  border: none;
  background: #0ea5e9;
  color: #ffffff;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.shared-login-btn:hover {
  background: #0284c7;
}

.shared-instruction {
  margin: 0;
  font-size: 0.86rem;
  color: #334155;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #0ea5e9;
  border-radius: 10px;
  padding: 12px 14px;
  line-height: 1.6;
  white-space: pre-wrap;
}

/* ── 会话气泡列表：与正常会话一致的布局 ── */
.shared-history {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 200px;
  max-height: calc(100vh - 280px);
  overflow-y: auto;
}

.shared-history-loading {
  border: none;
  padding: 32px 0;
  background: transparent;
}

.shared-empty {
  margin: 32px 0;
  text-align: center;
  color: #94a3b8;
  font-size: 0.82rem;
}

.shared-load-more {
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 18px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.shared-load-more:hover:not(:disabled) {
  border-color: #0ea5e9;
  color: #0ea5e9;
}

.shared-load-more:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 气泡（规格取自 chat-view 的 message-wrapper / message-bubble） */
.message-wrapper {
  display: flex;
  max-width: min(78%, 720px);
}

.role-user {
  align-self: flex-end;
}

.role-assistant {
  align-self: flex-start;
}

.message-stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.role-user .message-stack {
  align-items: flex-end;
}

.role-assistant .message-stack {
  align-items: flex-start;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 18px;
  color: #334155;
  font-size: 0.72rem;
  line-height: 1;
}

.role-user .message-meta {
  justify-content: flex-end;
}

.message-time {
  color: #475569;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.message-author {
  font-weight: 650;
  color: #0f172a;
  white-space: nowrap;
}

.message-bubble {
  padding: 13px 18px;
  border-radius: 16px;
  font-size: 0.95rem;
  line-height: 1.65;
  color: #1f2937;
  border: 1px solid #d6d3d1;
  background: #f8f7f5;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.role-user .message-bubble {
  border-top-right-radius: 14px;
}

.role-assistant .message-bubble {
  background: #ffffff;
}

.msg-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.shared-msg-unsupported {
  margin: 0;
  font-size: 0.82rem;
  color: #94a3b8;
  font-style: italic;
}

/* ── 邀请输入 ── */
.shared-input-area {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 20px;
}

.shared-input-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.shared-name-input,
.shared-content-input {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  padding: 10px 12px;
  font-size: 0.84rem;
  font-family: inherit;
  color: #0f172a;
  outline: none;
  transition: border-color 0.15s ease;
}

.shared-name-input:focus,
.shared-content-input:focus {
  border-color: #0ea5e9;
}

.shared-content-input {
  resize: vertical;
  min-height: 120px;
  line-height: 1.6;
}

.shared-submit-btn {
  align-self: flex-end;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  border-radius: 9px;
  border: none;
  background: #0ea5e9;
  color: #ffffff;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s ease;
}

.shared-submit-btn:hover:not(:disabled) {
  background: #0284c7;
}

.shared-submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.shared-submit-error {
  margin: 0;
  font-size: 0.76rem;
  color: #dc2626;
}

.shared-input-hint {
  margin: 0;
  font-size: 0.72rem;
  color: #94a3b8;
}

.shared-receipt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 28px 16px;
  text-align: center;
}

.shared-receipt-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: #f0fdf4;
  color: #16a34a;
  display: flex;
  align-items: center;
  justify-content: center;
}

.shared-receipt h2 {
  margin: 0;
  font-size: 1rem;
  color: #166534;
}

.shared-receipt p {
  margin: 0;
  font-size: 0.82rem;
  color: #475569;
  line-height: 1.5;
}

.shared-receipt-meta {
  font-size: 0.7rem !important;
  color: #94a3b8 !important;
}

.spin {
  animation: shared-spin 1s linear infinite;
}

@keyframes shared-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
