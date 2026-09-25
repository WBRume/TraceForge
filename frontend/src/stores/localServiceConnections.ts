import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ServiceConnection = {
  resource_id?: string
  backend: 'opencode' | 'dsh'
  service_url: string
  resource_service_url: string
  host_token?: string
  agent_token?: string
  agent_username?: string
}

// Credentials live only in this renderer's memory, never localStorage.
export const useLocalServiceConnectionsStore = defineStore('localServiceConnections', () => {
  const checked = ref<Record<string, ServiceConnection>>({})
  function save(key: string, connection: ServiceConnection) {
    checked.value[key] = { ...connection }
  }
  function matches(key: string, connection: ServiceConnection) {
    return JSON.stringify(checked.value[key]) === JSON.stringify(connection)
  }
  function invalidate(key: string) { delete checked.value[key] }
  return { checked, save, matches, invalidate }
})
