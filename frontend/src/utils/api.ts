import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { getSddDesktop } from '@/utils/runtime'

export const DEFAULT_SERVER_URL = 'http://localhost:8000'

export const normalizeServerUrl = (value: string): string => {
  const normalized = String(value || DEFAULT_SERVER_URL).trim().replace(/\/+$/, '')
  return normalized || DEFAULT_SERVER_URL
}

export const buildApiBaseUrl = (serverUrl: string): string => `${normalizeServerUrl(serverUrl)}/api`

const api = axios.create({
  baseURL: buildApiBaseUrl(DEFAULT_SERVER_URL),
  timeout: 15000,
})

export const setApiServerUrl = (serverUrl: string): string => {
  const normalized = normalizeServerUrl(serverUrl)
  api.defaults.baseURL = buildApiBaseUrl(normalized)
  localStorage.setItem('sdd_server_url', normalized)
  return normalized
}

export const getApiServerUrl = (): string => {
  const baseURL = String(api.defaults.baseURL || '')
  if (baseURL.endsWith('/api')) {
    return baseURL.slice(0, -4)
  }
  return normalizeServerUrl(localStorage.getItem('sdd_server_url') || DEFAULT_SERVER_URL)
}

export const initializeApiFromDesktopConfig = async (): Promise<void> => {
  const desktop = getSddDesktop()
  setApiServerUrl(DEFAULT_SERVER_URL)
  if (!desktop) {
    return
  }

  const config = await desktop.config.getConfig()
  if (config.token) {
    const authStore = useAuthStore()
    authStore.setToken(config.token)
  }
}

// Request interceptor: add auth token
api.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`
  }
  return config
})

// Response interceptor: handle 401s
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const authStore = useAuthStore()
      authStore.logout()
    }
    return Promise.reject(error)
  }
)

export default api
