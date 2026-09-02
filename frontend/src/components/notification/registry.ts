/**
 * 通知类型注册表(与后端 app/domains/notification/types.py 对应)
 *
 * 接入新通知来源只需:
 * 1. 后端 types.py 注册类型元信息;
 * 2. 这里 registerNotificationType 注册点击跳转解析。
 * 未注册的类型走默认行为:点击仅消费(删除)不跳转。
 */
import type { AppNotificationItem } from '@/stores/notification'

export interface NotificationTypeDef {
  type: string
  /** 由通知内容解析点击后跳转的路由;返回 null 表示该类型无跳转 */
  resolveTarget?: (item: AppNotificationItem) => string | null
}

const registry = new Map<string, NotificationTypeDef>()

export function registerNotificationType(def: NotificationTypeDef): void {
  registry.set(def.type, def)
}

export function getNotificationTypeDef(type: string): NotificationTypeDef | undefined {
  return registry.get(type)
}

export function resolveNotificationTarget(item: AppNotificationItem): string | null {
  return getNotificationTypeDef(item.type)?.resolveTarget?.(item) ?? null
}

const resolveTaskChatTarget = (item: AppNotificationItem): string | null => {
  const payload = item.payload || {}
  const taskId = String(payload.task_id || '')
  const workspaceId = String(payload.workspace_id || '')
  return taskId && workspaceId ? `/ws/${workspaceId}/chat/${taskId}` : null
}

registerNotificationType({
  type: 'pre_input_mention',
  resolveTarget: resolveTaskChatTarget,
})

registerNotificationType({
  type: 'pre_input_submitted',
  resolveTarget: resolveTaskChatTarget,
})

registerNotificationType({
  type: 'task_message',
  resolveTarget: resolveTaskChatTarget,
})
