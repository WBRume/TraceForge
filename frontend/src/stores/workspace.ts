import { ref } from 'vue'
import { defineStore } from 'pinia'
import api from '@/utils/api'
import type { SavedAvatar } from '@/utils/avatar'

export const useWorkspaceStore = defineStore('workspace', () => {
  const currentWorkspace = ref<any>(null)
  const workspaces = ref<any[]>([])
  let currentRequest = 0
  
  async function fetchWorkspaces(selectDefault = true) {
    const res = await api.get('/workspaces')
    workspaces.value = res.data
    
    // 如果没有选中，默认选第一个
    if (selectDefault && !currentWorkspace.value && res.data.length > 0) {
      setCurrent(res.data[0])
    }
    return res.data
  }
  
  function setCurrent(ws: any) {
    currentRequest++
    currentWorkspace.value = ws
    localStorage.setItem('sdd_ws_id', ws.id)
  }

  function setWorkspaceAvatar(id: string, avatar: SavedAvatar) {
    const listed = workspaces.value.find(workspace => workspace.id === id)
    if (listed) Object.assign(listed, avatar)
    if (currentWorkspace.value?.id === id) Object.assign(currentWorkspace.value, avatar)
  }
  
  async function restoreCurrent(wsId = localStorage.getItem('sdd_ws_id')) {
    if (wsId) {
      const request = ++currentRequest
      try {
        const res = await api.get(`/workspaces/${encodeURIComponent(wsId)}`)
        if (request === currentRequest) setCurrent(res.data)
      } catch (e) {
        if (request !== currentRequest) return
        currentWorkspace.value = null
        if (localStorage.getItem('sdd_ws_id') === wsId) localStorage.removeItem('sdd_ws_id')
      }
    }
  }

  return { currentWorkspace, workspaces, fetchWorkspaces, setCurrent, setWorkspaceAvatar, restoreCurrent }
})
