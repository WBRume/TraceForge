import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/utils/api'

/**
 * 系统配置（DB 支撑的功能开关）。
 * - projectProductManagementEnabled：新建工作区时是否启用“项目管理/产品管理”选择功能。
 *   开启：按既有流程选择项目与产品。
 *   关闭（默认）：屏蔽项目管理/产品管理页面；新建工作区直接填写项目与产品名称，并可选仓库与分支。
 * - workspaceRootDir：工作区根目录。为空时保持原有逻辑（用户手动输入根目录）；
 *   设置后新建工作区路径默认为 根目录/workspace/工作区名称，且仅允许位于该目录之内。
 */
export const useSystemConfigStore = defineStore('systemConfig', () => {
  const projectProductManagementEnabled = ref(false)
  const workspaceRootDir = ref('')
  const loaded = ref(false)
  let pending: Promise<void> | null = null

  const load = async (force = false): Promise<void> => {
    if (loaded.value && !force) return
    if (pending) return pending
    pending = (async () => {
      try {
        const res = await api.get('/system-configs')
        const data = res.data || {}
        if (typeof data.project_product_management_enabled === 'boolean') {
          projectProductManagementEnabled.value = data.project_product_management_enabled
        }
        if (typeof data.workspace_root_dir === 'string') {
          workspaceRootDir.value = data.workspace_root_dir
        }
        loaded.value = true
      } catch {
        // 拉取失败时保持默认，不阻塞主流程
      } finally {
        pending = null
      }
    })()
    return pending
  }

  const updateProjectProductManagementEnabled = async (value: boolean): Promise<void> => {
    const res = await api.put('/system-configs/project_product_management_enabled', { value })
    const data = res.data || {}
    if (typeof data.project_product_management_enabled === 'boolean') {
      projectProductManagementEnabled.value = data.project_product_management_enabled
    }
    loaded.value = true
  }

  const updateWorkspaceRootDir = async (value: string): Promise<void> => {
    const res = await api.put('/system-configs/workspace_root_dir', { value })
    const data = res.data || {}
    if (typeof data.workspace_root_dir === 'string') {
      workspaceRootDir.value = data.workspace_root_dir
    }
    loaded.value = true
  }

  return {
    projectProductManagementEnabled,
    workspaceRootDir,
    loaded,
    load,
    updateProjectProductManagementEnabled,
    updateWorkspaceRootDir,
  }
})
