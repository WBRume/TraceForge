/**
 * 分享链接管理（登录发起人）：创建 / 列表 / 撤销。
 */
import { computed, ref, shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'

export type SessionShareMode = 'READ' | 'INPUT'

export type SessionShareItem = {
  id: string
  mode: string
  instruction_text: string | null
  session_generation: number
  expires_at: string
  revoked_at: string | null
  revoke_reason: string | null
  created_at: string
  status: string
  /** 明文令牌 + 服务端拼好的链接（与成员邀请链接对齐，随时可复制） */
  token: string | null
  share_url: string | null
}

export type CreatedShare = {
  id: string
  mode: string
  expires_at: string
  instruction_text: string | null
  session_generation: number
  share_token: string
  share_url: string
}

export function useTaskSessionShares(options: {
  getWorkspaceId: () => string
  getTaskId: () => string
}) {
  const { t } = useI18n()

  const shares = shallowRef<SessionShareItem[]>([])
  const sharesLoading = ref(false)
  const creating = ref(false)
  const revokingIds = ref<Set<string>>(new Set())

  const activeShares = computed(() =>
    shares.value.filter((item) => item.status === 'ACTIVE')
  )
  const pendingInputShareCount = computed(() =>
    shares.value.filter((item) => item.status === 'ACTIVE' && item.mode === 'INPUT').length
  )

  const loadShares = async () => {
    const taskId = options.getTaskId()
    if (!taskId) return
    sharesLoading.value = true
    try {
      const res = await api.get(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/session-shares`
      )
      shares.value = res.data?.items || []
    } catch {
      // 列表加载失败不打断会话；弹窗内展示错误即可
      shares.value = []
    } finally {
      sharesLoading.value = false
    }
  }

  const createShare = async (payload: {
    mode: SessionShareMode
    expires_in_days: number
    instruction_text?: string | null
  }): Promise<CreatedShare | null> => {
    const taskId = options.getTaskId()
    if (!taskId || creating.value) return null
    creating.value = true
    try {
      const res = await api.post(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/session-shares`,
        payload
      )
      await loadShares()
      return res.data as CreatedShare
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status
      ElMessage.error(
        status === 403
          ? t('share.errors.no_permission')
          : t('share.errors.create_failed')
      )
      return null
    } finally {
      creating.value = false
    }
  }

  const revokeShare = async (shareId: string) => {
    const taskId = options.getTaskId()
    if (!taskId || revokingIds.value.has(shareId)) return false
    revokingIds.value = new Set(revokingIds.value).add(shareId)
    try {
      await api.delete(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/session-shares/${shareId}`
      )
      await loadShares()
      return true
    } catch {
      ElMessage.error(t('share.errors.revoke_failed'))
      return false
    } finally {
      const next = new Set(revokingIds.value)
      next.delete(shareId)
      revokingIds.value = next
    }
  }

  /** 拼接绝对分享地址（复制给外部访客）。 */
  const buildAbsoluteShareUrl = (shareUrl: string): string => {
    const { origin } = window.location
    return `${origin}${shareUrl}`
  }

  return {
    shares,
    sharesLoading,
    creating,
    revokingIds,
    activeShares,
    pendingInputShareCount,
    loadShares,
    createShare,
    revokeShare,
    buildAbsoluteShareUrl,
  }
}
