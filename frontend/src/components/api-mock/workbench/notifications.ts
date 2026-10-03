import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { formatApiError } from '@/utils/error'
import type { ApiMockLockedDetail, ApiMockErrorBody } from './types'

export function useWorkbenchNotifications() {
  const { t } = useI18n()
  const notifySuccess = (text: string) => {
    ElMessage({
      type: 'success',
      message: text,
      duration: 1500,
      grouping: true,
    })
  }

  const notifyError = (err: unknown, fallback: string) => {
    ElMessage({
      type: 'error',
      message: formatApiError(err, fallback, t),
      duration: 2600,
      grouping: true,
    })
  }

  const notifyProjectSwaggerLocked = () => {
    ElMessage({
      type: 'warning',
      message: t('api_mock.ai_auto_mock_locked_project_swagger_mutation'),
      duration: 2600,
      grouping: true,
    })
  }

  const notifyCurrentEndpointCreateLocked = () => {
    ElMessage({
      type: 'warning',
      message: t('api_mock.ai_auto_mock_locked_current_endpoint'),
      duration: 2600,
      grouping: true,
    })
  }

  const isConflictError = (err: unknown) => {
    const status = Number((err as { response?: { status?: number } } | null)?.response?.status || 0)
    return status === 409
  }

  const isAutoMockProjectLockError = (err: unknown) => {
    const status = Number((err as { response?: { status?: number } } | null)?.response?.status || 0)
    if (status !== 409) return false
    const detail = parseLockedDetail(err)
    return String(detail?.code || '') === 'ai_auto_mock_locked_project_swagger_mutation'
  }

  const isAutoMockEndpointLockError = (err: unknown) => {
    const status = Number((err as { response?: { status?: number } } | null)?.response?.status || 0)
    if (status !== 409) return false
    const detail = parseLockedDetail(err)
    return String(detail?.code || '') === 'ai_auto_mock_locked_current_endpoint'
  }

  const parseLockedDetail = (err: unknown): ApiMockLockedDetail | null => {
    const detail = ((err as { response?: { data?: ApiMockErrorBody } })?.response?.data?.detail || null) as
      | ApiMockLockedDetail
      | string
      | null
    if (!detail || typeof detail === 'string') return null
    return detail
  }

  return { notifySuccess, notifyError, notifyProjectSwaggerLocked, notifyCurrentEndpointCreateLocked, isConflictError, isAutoMockProjectLockError, isAutoMockEndpointLockError, parseLockedDetail }
}

export type WorkbenchNotifications = ReturnType<typeof useWorkbenchNotifications>
