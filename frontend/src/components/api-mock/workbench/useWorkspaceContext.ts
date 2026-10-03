import { computed, onBeforeUnmount, ref, watch } from 'vue'
import api from '@/utils/api'
import type { TaskOption, WorkspaceMemberProfile, OnlinePresenceUser, PermissionFlags } from './types'
import type { Ref } from 'vue'

export function useWorkspaceContext(wsId: Ref<string>) {
  let generation = 0
  watch(wsId, () => {
    generation += 1
    tasks.value = []
    permissions.value = null
    permissionsReady.value = false
    workspaceMemberMap.value = {}
    pageError.value = ''
  }, { flush: 'sync' })
  onBeforeUnmount(() => { generation += 1 })

  const tasks = ref<TaskOption[]>([])

  const permissions = ref<PermissionFlags | null>(null)

  const workspaceMemberMap = ref<Record<string, OnlinePresenceUser>>({})

  const permissionsReady = ref(false)

  const pageError = ref('')

  const canView = computed(() => Boolean(permissions.value?.view_api_mock))

  const canManage = computed(() => Boolean(permissions.value?.manage_api_mock))

  const canPublish = computed(() => Boolean(permissions.value?.publish_api_mock))

  const loadPermissions = async () => {
    const version = generation
    const workspaceId = wsId.value
    const res = await api.get(`/workspaces/${workspaceId}/permissions/me`)
    if (version !== generation) return
    permissions.value = res.data?.permissions || null
    permissionsReady.value = true
  }

  const loadWorkspaceMembers = async () => {
    const version = generation
    const workspaceId = wsId.value
    const resultMap: Record<string, OnlinePresenceUser> = {}
    const pageSize = 100
    let page = 1
    while (true) {
      const res = await api.get(`/workspaces/${workspaceId}/members`, { params: { page, page_size: pageSize } })
      const owner = (res.data?.owner || null) as WorkspaceMemberProfile | null
      if (version !== generation) return
      const items = Array.isArray(res.data?.items) ? (res.data.items as WorkspaceMemberProfile[]) : []
      const merged = owner ? [owner, ...items] : items
      for (const member of merged) {
        if (!member?.user_id) continue
        resultMap[member.user_id] = {
          id: member.user_id,
          displayName: member.display_name || member.email || member.user_id,
          email: member.email || '',
          avatarSvg: member.avatar_svg || null,
          avatarUrl: member.avatar_url || null,
        }
      }
      if (items.length < pageSize) break
      page += 1
    }
    workspaceMemberMap.value = resultMap
  }

  const loadTasks = async () => {
    const version = generation
    const workspaceId = wsId.value
    const merged: TaskOption[] = []
    const pageSize = 100
    let page = 1
    while (true) {
      const res = await api.get(`/workspaces/${workspaceId}/tasks`, { params: { page, page_size: pageSize } })
      if (version !== generation) return
      const items = Array.isArray(res.data?.items) ? res.data.items : []
      for (const item of items) {
        if (item?.id && item?.name) {
          merged.push({ id: item.id, name: item.name })
        }
      }
      if (items.length < pageSize) break
      page += 1
    }
    tasks.value = merged
  }

  return { tasks, permissions, workspaceMemberMap, permissionsReady, pageError, canView, canManage, canPublish, loadPermissions, loadWorkspaceMembers, loadTasks }
}

export type WorkspaceContext = ReturnType<typeof useWorkspaceContext>
