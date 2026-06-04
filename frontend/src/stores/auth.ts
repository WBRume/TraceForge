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
  created_at?: string
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('sdd_token'))
  const user = ref<AuthUser | null>(null)
  
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
    localStorage.removeItem('sdd_token')
  }

  function setUser(nextUser: AuthUser | null) {
    user.value = nextUser
  }
  
  async function fetchCurrentUser() {
    if (!token.value) return null
    try {
      const res = await api.get('/auth/me')
      user.value = res.data as AuthUser
      return res.data
    } catch (e) {
      clearSession()
      return null
    }
  }

  return { token, user, isAuthenticated, setToken, logout, clearSession, setUser, fetchCurrentUser }
})
