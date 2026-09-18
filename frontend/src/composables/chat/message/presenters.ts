import { useI18n } from 'vue-i18n'

/** 消息展示辅助：作者名 / 身份判断 / 时间格式化。 */

export const formatMessageTime = (isoStr: string): string => {
  if (!isoStr) return ''
  return new Date(isoStr).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  })
}

export const createMessagePresenters = (options: { isCurrentUser: (msg: any) => boolean }) => {
  const { t } = useI18n()

  const isMessageWorkspaceExpert = (msg: any): boolean => (
    String(msg?.role || '').toLowerCase() === 'user' && Boolean(msg?.creator_is_workspace_expert)
  )

  const messageAuthorLabel = (msg: any): string => {
    const role = String(msg?.role || '').toLowerCase()
    if (role === 'assistant') return t('chat.ai_assistant_name')
    if (role === 'system') return 'System'
    if (options.isCurrentUser(msg)) return 'You'
    return String(msg?.creator_display_name || '').trim() || 'Member'
  }

  return {
    isMessageWorkspaceExpert,
    messageAuthorLabel,
  }
}
