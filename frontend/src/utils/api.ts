import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { isDesktop, getSddDesktop } from '@/utils/runtime'

export const DEFAULT_SERVER_URL =
  typeof window !== 'undefined' && !isDesktop() && !window.sddTaskFloat
    ? window.location.origin
    : 'http://localhost:8000'

export const normalizeServerUrl = (value: string): string => {
  const normalized = String(value || DEFAULT_SERVER_URL).trim().replace(/\/+$/, '')
  return normalized || DEFAULT_SERVER_URL
}

export const buildApiBaseUrl = (serverUrl: string): string => `${normalizeServerUrl(serverUrl)}/api`

const storedDesktopServer = isDesktop() ? localStorage.getItem('sdd_server_url') : null
const api = axios.create({
  baseURL: buildApiBaseUrl(storedDesktopServer ?? DEFAULT_SERVER_URL),
  timeout: 15000,
})

export const setApiServerUrl = (serverUrl: string, persist = true): string => {
  const normalized = normalizeServerUrl(serverUrl)
  api.defaults.baseURL = buildApiBaseUrl(normalized)
  if (persist) localStorage.setItem('sdd_server_url', normalized)
  window.dispatchEvent(new Event('sdd-server-changed'))
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
  if (!desktop) {
    setApiServerUrl(DEFAULT_SERVER_URL)
    return
  }

  const config = await desktop.config.getConfig()
  if (desktop.workspaceWindows?.isPrimary === false) {
    setApiServerUrl(localStorage.getItem('sdd_server_url') ?? config.serverUrl, false)
    return
  }
  setApiServerUrl(config.serverUrl)
  if (config.token) {
    const authStore = useAuthStore()
    authStore.setToken(config.token)
  }
}

// Request interceptor: add auth token
api.interceptors.request.use((config) => {
  config.headers.set('X-TraceForge-Client', isDesktop() || window.sddTaskFloat ? 'desktop' : 'web')
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
    if (error.response?.status === 401 && !window.sddTaskFloat) {
      const authStore = useAuthStore()
      authStore.logout()
    }
    return Promise.reject(error)
  }
)

export default api
