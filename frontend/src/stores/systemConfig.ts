import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/utils/api'

/**
 * 系统配置（DB 支撑的功能开关）。
 * - projectProductManagementEnabled：新建工作区时是否启用“项目管理/产品管理”选择功能。
 *   开启：按既有流程选择项目与产品。
 *   关闭（默认）：屏蔽项目管理/产品管理页面；新建工作区直接填写项目与产品名称并手动选择仓库分支。
 */
export const useSystemConfigStore = defineStore('systemConfig', () => {
  const projectProductManagementEnabled = ref(false)
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
        loaded.value = true
      } catch {
        // 拉取失败时保持默认（开启），不阻塞主流程
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

  return {
    projectProductManagementEnabled,
    loaded,
    load,
    updateProjectProductManagementEnabled,
  }
})
