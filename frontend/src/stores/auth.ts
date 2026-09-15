import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api from '@/utils/api'
import router from '@/router'

type AuthUser = {
  id: string
  email: string
  display_name: string
  avatar_url?: string | null
  avatar_svg?: string | null
  is_admin?: boolean
  created_at?: string
  /** 已绑定的三方 provider 名列表（GET /auth/me 增量字段，§2.3.2 接口 11） */
  bound_providers?: string[]
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('sdd_token'))
  const user = ref<AuthUser | null>(null)
  const boundProviders = ref<string[]>([])
  
  const isAuthenticated = computed(() => !!token.value)
  
  function setToken(newToken: string) {
    if (token.value !== newToken) {
      user.value = null
    }
    token.value = newToken
    localStorage.setItem('sdd_token', newToken)
  }
  
  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('sdd_token')
    router.push('/')
  }

  function clearSession() {
    token.value = null
    user.value = null
    boundProviders.value = []
    localStorage.removeItem('sdd_token')
  }

  function setUser(nextUser: AuthUser | null) {
    user.value = nextUser
  }

  function setBoundProviders(providers: string[]) {
    boundProviders.value = providers
  }

  async function fetchCurrentUser() {
    if (!token.value) return null
    try {
      const res = await api.get('/auth/me')
      user.value = res.data as AuthUser
      boundProviders.value = (res.data as AuthUser).bound_providers ?? []
      return res.data
    } catch (e) {
      clearSession()
      return null
    }
  }

  return { token, user, boundProviders, isAuthenticated, setToken, logout, clearSession, setUser, setBoundProviders, fetchCurrentUser }
})
