import { computed, ref } from 'vue'
import api from '@/utils/api'

/**
 * 工作区上下文：工作区信息、当前用户权限与专家身份。
 * 权限判定集中在这一处，动作模块通过注入的 computed 消费。
 */
export function useWorkspaceContext(options: {
  getWorkspaceId: () => string
}) {
  const currentWorkspace = ref<any>(null)
  const workspacePermissions = ref<any>(null)
  const workspaceCurrentUserIsExpert = ref(false)

  const loadWorkspace = async () => {
    const wsId = options.getWorkspaceId()
    const [wsRes, permissionRes] = await Promise.all([
      api.get(`/workspaces/${wsId}`),
      api.get(`/workspaces/${wsId}/permissions/me`),
    ])
    currentWorkspace.value = wsRes.data
    workspacePermissions.value = permissionRes.data?.permissions || null
    workspaceCurrentUserIsExpert.value = Boolean(permissionRes.data?.is_expert || wsRes.data?.my_is_expert)
  }

  const isWorkspaceExpert = () => (
    workspaceCurrentUserIsExpert.value || Boolean(currentWorkspace.value?.my_is_expert)
  )

  const canCreateTask = computed(() => Boolean(workspacePermissions.value?.create_task))
  const canStartTask = computed(() => Boolean(workspacePermissions.value?.start_task))
  const canManageTaskStatus = computed(() => Boolean(workspacePermissions.value?.manage_task_status))
  const canDeleteTask = computed(() => Boolean(workspacePermissions.value?.delete_task))
  const canExportTask = computed(() => Boolean(workspacePermissions.value?.export_task))
  const canEditSuperpowersDocs = computed(() => (
    Boolean(workspacePermissions.value?.upload_task_spec || workspacePermissions.value?.manage_task_status)
  ))

  return {
    currentWorkspace,
    workspacePermissions,
    workspaceCurrentUserIsExpert,
    loadWorkspace,
    isWorkspaceExpert,
    canCreateTask,
    canStartTask,
    canManageTaskStatus,
    canDeleteTask,
    canExportTask,
    canEditSuperpowersDocs,
  }
}
