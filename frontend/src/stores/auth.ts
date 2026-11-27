import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api from '@/utils/api'
import router from '@/router'
import { getSddDesktop } from '@/utils/runtime'

export type AssetDisplayMode = 'table' | 'canvas'

type AuthUser = {
  id: string
  email: string
  display_name: string
  avatar_url?: string | null
  avatar_svg?: string | null
  is_admin?: boolean
  created_at?: string
  asset_display_mode?: AssetDisplayMode
  /** 已绑定的三方 provider 名列表（GET /auth/me 增量字段） */
  bound_providers?: string[]
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('sdd_token'))
  const user = ref<AuthUser | null>(null)
  const boundProviders = ref<string[]>([])
  const savingAssetDisplay = ref(false)
  const assetDisplayMode = computed<AssetDisplayMode>(() => user.value?.asset_display_mode ?? 'table')
  
  const isAuthenticated = computed(() => !!token.value)
  
  function setToken(newToken: string) {
    adoptToken(newToken)
    localStorage.setItem('sdd_token', newToken)
  }

  function adoptToken(nextToken: string | null) {
    if (token.value === nextToken) return
    user.value = null
    boundProviders.value = []
    token.value = nextToken
  }
  
  /**
   * 清除 Electron 桌面端持久化的 token（%APPDATA%/frontend/config.json）。
   * 登录弹窗会把 token 写入桌面配置，登出若不同步清理，
   * 刷新 / 重启（initializeApiFromDesktopConfig）和 loadLocalConfig 都会把
   * 旧 token 恢复回来，表现为"登出无效，刷新又登录"。
   */
  function clearDesktopPersistedToken() {
    const desktop = getSddDesktop()
    if (!desktop) return
    void desktop.config.setConfig({ token: null }).catch((error: unknown) => {
      console.error('Failed to clear persisted desktop token', error)
    })
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('sdd_token')
    clearDesktopPersistedToken()
    router.push('/')
  }

  function clearSession() {
    token.value = null
    user.value = null
    boundProviders.value = []
    localStorage.removeItem('sdd_token')
    clearDesktopPersistedToken()
  }

  function setUser(nextUser: AuthUser | null) {
    user.value = nextUser
  }

  function setBoundProviders(providers: string[]) {
    boundProviders.value = providers
  }

  async function setAssetDisplayMode(mode: AssetDisplayMode) {
    const actor = user.value?.id
    const currentToken = token.value
    if (!actor || savingAssetDisplay.value || mode === assetDisplayMode.value) return
    savingAssetDisplay.value = true
    try {
      const { data } = await api.put<{ mode: AssetDisplayMode }>('/auth/me/asset-display', { mode })
      if (token.value === currentToken && user.value?.id === actor) {
        user.value = { ...user.value, asset_display_mode: data.mode }
      }
    } finally {
      savingAssetDisplay.value = false
    }
  }

  async function fetchCurrentUser() {
    const currentToken = token.value
    if (!currentToken) return null
    try {
      const res = await api.get('/auth/me')
      if (token.value !== currentToken) return null
      user.value = res.data as AuthUser
      boundProviders.value = (res.data as AuthUser).bound_providers ?? []
      return res.data
    } catch (e) {
      if (token.value === currentToken) clearSession()
      return null
    }
  }

  return { token, user, boundProviders, isAuthenticated, assetDisplayMode, savingAssetDisplay, setAssetDisplayMode,
    setToken, adoptToken, logout, clearSession, setUser, setBoundProviders, fetchCurrentUser }
})
