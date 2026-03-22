import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api from '@/utils/api'
import router from '@/router'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('sdd_token'))
  const user = ref<any>(null)
  
  const isAuthenticated = computed(() => !!token.value)
  
  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('sdd_token', newToken)
  }
  
  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('sdd_token')
    router.push('/login')
  }
  
  async function fetchCurrentUser() {
    if (!token.value) return null
    try {
      const res = await api.get('/auth/me')
      user.value = res.data
      return res.data
    } catch (e) {
      logout()
      return null
    }
  }

  return { token, user, isAuthenticated, setToken, logout, fetchCurrentUser }
})
