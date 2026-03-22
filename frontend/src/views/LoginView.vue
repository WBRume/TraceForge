<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import api from '@/utils/api'

const router = useRouter()
const authStore = useAuthStore()

const isLoginMode = ref(true)
const loading = ref(false)
const errorMessage = ref('')

const form = ref({
  email: '',
  password: '',
  displayName: ''
})

const toggleMode = () => {
  isLoginMode.value = !isLoginMode.value
  errorMessage.value = ''
}

const handleSubmit = async () => {
  loading.value = true
  errorMessage.value = ''
  
  try {
    if (isLoginMode.value) {
      // Login
      const params = new URLSearchParams()
      params.append('username', form.value.email)
      params.append('password', form.value.password)
      
      const res = await api.post('/auth/login', params)
      authStore.setToken(res.data.access_token)
      await authStore.fetchCurrentUser()
      router.push('/workspaces')
      
    } else {
      // Register
      await api.post('/auth/register', {
        email: form.value.email,
        password: form.value.password,
        display_name: form.value.displayName || form.value.email.split('@')[0]
      })
      // Auto login after register
      const params = new URLSearchParams()
      params.append('username', form.value.email)
      params.append('password', form.value.password)
      const res = await api.post('/auth/login', params)
      authStore.setToken(res.data.access_token)
      await authStore.fetchCurrentUser()
      router.push('/workspaces')
    }
  } catch (error: any) {
    errorMessage.value = error.response?.data?.detail || 'Authentication failed'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card glass-panel">
      <div class="auth-header">
        <h2>{{ isLoginMode ? 'Welcome Back' : 'Create Account' }}</h2>
        <p class="subtitle">SDD Native Platform</p>
      </div>

      <form @submit.prevent="handleSubmit" class="auth-form">
        <div v-if="!isLoginMode" class="form-group">
          <label for="displayName">Display Name</label>
          <input 
            id="displayName" 
            v-model="form.displayName" 
            type="text" 
            class="input-field" 
            placeholder="How should we call you?"
          >
        </div>

        <div class="form-group">
          <label for="email">Email</label>
          <input 
            id="email" 
            v-model="form.email" 
            type="email" 
            required 
            class="input-field"
            placeholder="name@company.com"
          >
        </div>

        <div class="form-group">
          <label for="password">Password</label>
          <input 
            id="password" 
            v-model="form.password" 
            type="password" 
            required 
            class="input-field"
            placeholder="••••••••"
          >
        </div>

        <div v-if="errorMessage" class="error-msg">
          {{ errorMessage }}
        </div>

        <button type="submit" class="btn-primary auth-submit" :disabled="loading">
          {{ loading ? 'Processing...' : (isLoginMode ? 'Sign In' : 'Sign Up') }}
        </button>
      </form>

      <div class="auth-footer">
        <p>
          {{ isLoginMode ? "Don't have an account?" : "Already have an account?" }}
          <a href="#" @click.prevent="toggleMode">
            {{ isLoginMode ? 'Sign up' : 'Sign in' }}
          </a>
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-bg-base);
  background-image: radial-gradient(circle at center, var(--color-primary-50), transparent 70%);
}

.auth-card {
  width: 100%;
  max-width: 420px;
  padding: var(--space-8);
  margin: var(--space-4);
  /* Make it pop slightly more than default glass */
  background-color: rgba(255, 255, 255, 0.85);
  box-shadow: var(--shadow-lg);
}

.auth-header {
  text-align: center;
  margin-bottom: var(--space-6);
}

.auth-header h2 {
  font-size: 1.75rem;
  margin-bottom: var(--space-1);
}

.subtitle {
  color: var(--color-text-muted);
  font-size: 0.95rem;
  margin: 0;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-body);
}

.input-field {
  padding: 12px 16px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  font-size: 1rem;
  transition: all var(--transition-fast);
  font-family: inherit;
  background: var(--color-surface-white);
}

.input-field:focus {
  border-color: var(--color-primary-500);
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}

.auth-submit {
  margin-top: var(--space-2);
  padding: 14px;
  font-size: 1rem;
}

.error-msg {
  color: var(--color-accent-rose);
  font-size: 0.875rem;
  text-align: center;
  background-color: rgba(244, 63, 94, 0.1);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
}

.auth-footer {
  margin-top: var(--space-6);
  text-align: center;
  font-size: 0.9rem;
  color: var(--color-text-muted);
}
</style>
