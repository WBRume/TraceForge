import { ref } from 'vue'
import { defineStore } from 'pinia'
import api from '@/utils/api'

export const useWorkspaceStore = defineStore('workspace', () => {
  const currentWorkspace = ref<any>(null)
  const workspaces = ref<any[]>([])
  
  async function fetchWorkspaces() {
    const res = await api.get('/workspaces')
    workspaces.value = res.data
    
    // 如果没有选中，默认选第一个
    if (!currentWorkspace.value && res.data.length > 0) {
      currentWorkspace.value = res.data[0]
      localStorage.setItem('sdd_ws_id', res.data[0].id)
    }
    return res.data
  }
  
  function setCurrent(ws: any) {
    currentWorkspace.value = ws
    localStorage.setItem('sdd_ws_id', ws.id)
  }
  
  async function restoreCurrent() {
    const wsId = localStorage.getItem('sdd_ws_id')
    if (wsId) {
      try {
        const res = await api.get(`/workspaces/${wsId}`)
        currentWorkspace.value = res.data
      } catch (e) {
        currentWorkspace.value = null
        localStorage.removeItem('sdd_ws_id')
      }
    }
  }

  return { currentWorkspace, workspaces, fetchWorkspaces, setCurrent, restoreCurrent }
})
