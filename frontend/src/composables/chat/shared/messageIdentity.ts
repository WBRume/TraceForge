/**
 * 消息身份与规范化：去重键、客户端消息 ID、历史消息映射。
 * 纯函数，无状态；被消息存储、历史加载、会话快照共同复用。
 */

export const generateClientMessageId = (): string => {
  const cryptoApi = globalThis.crypto
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID()
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export const messageIdentity = (msg: any): string => {
  const clientMessageId = String(msg?.client_message_id || '').trim()
  if (clientMessageId) return `client:${clientMessageId}`
  const id = String(msg?.id || '').trim()
  return id ? `id:${id}` : ''
}

/** 按身份合并重复项（后者字段覆盖前者），无身份项原样保留。 */
export const dedupeMessages = (items: any[]): any[] => {
  const indexByKey = new Map<string, number>()
  const result: any[] = []
  for (const item of items) {
    const key = messageIdentity(item)
    if (!key) {
      result.push(item)
      continue
    }
    const existingIndex = indexByKey.get(key)
    if (existingIndex === undefined) {
      indexByKey.set(key, result.length)
      result.push(item)
      continue
    }
    result[existingIndex] = {
      ...result[existingIndex],
      ...item,
    }
  }
  return result
}

export type ChatMessageFields = {
  id: string
  role: string
  content: string
  created_at: string
  message_type: string
  creator_id: string | null
  creator_display_name: string | null
  creator_is_workspace_expert: boolean
  creator_avatar_url: string | null
  creator_avatar_svg: string | null
  client_message_id: string | null
  decision_id: string | null
  metadata: any
  session_turn_id: string | null
  session_generation: number | null
  can_undo: boolean
}

/** 后端消息（history / WS / 快照）→ 前端气泡统一形状。 */
export const mapHistoryMessages = (hMessages: any[]): ChatMessageFields[] => hMessages.map((m: any) => ({
  id: m.id,
  role: m.role,
  content: m.content,
  created_at: m.created_at,
  message_type: m.type || 'text',
  creator_id: m.creator_id || null,
  creator_display_name: m.creator_display_name || null,
  creator_is_workspace_expert: Boolean(m.creator_is_workspace_expert),
  creator_avatar_url: m.creator_avatar_url || null,
  creator_avatar_svg: m.creator_avatar_svg || null,
  client_message_id: m.client_message_id || null,
  decision_id: m.decision_id || null,
  metadata: m.metadata || null,
  session_turn_id: m.session_turn_id || null,
  session_generation: m.session_generation ?? null,
  can_undo: Boolean(m.can_undo),
}))
