import { formatApiError } from '@/utils/error'

export const isCanceledRequest = (error: unknown): boolean => (
  (error as { code?: string })?.code === 'ERR_CANCELED'
  || (error as { name?: string })?.name === 'CanceledError'
)

export const isForbiddenError = (error: unknown): boolean => {
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === 403
}

/**
 * 统一的动作错误文案解析：403 显示无权限文案，其余走通用 API 错误格式化。
 */
export const createResolveActionError = (t: (key: string) => string) => (
  error: unknown,
  fallbackKey: string,
  noPermissionKey: string,
): string => {
  if (isForbiddenError(error)) {
    return t(noPermissionKey)
  }
  return formatApiError(error, t(fallbackKey), t)
}
