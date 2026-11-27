<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loader2 } from '@/components/icons'
import { useAuthStore } from '@/stores/auth'
import api, { getApiServerUrl } from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { getSddDesktop } from '@/utils/runtime'
import OAuthProviderButtons from './OAuthProviderButtons.vue'
import type { PortalAuthMode } from './portalAuthDialog'

const mode = defineModel<PortalAuthMode | null>({ required: true })
const { t } = useI18n()
const authStore = useAuthStore()
const desktop = getSddDesktop()
const dialogId = useId()
const dialog = useTemplateRef<HTMLElement>('dialog')
const isLoginMode = computed(() => mode.value === 'login')
const authLoading = shallowRef(false)
const authError = shallowRef('')
const authModalOverlayArmed = shallowRef(false)
const authForm = ref({
  email: '',
  password: '',
  displayName: ''
})
const LAST_LOGIN_EMAIL_KEY = 'sdd_last_login_email'

watch(mode, (nextMode, previousMode) => {
  if (!nextMode) return
  authError.value = ''
  authForm.value.password = ''
  if (nextMode === 'login' && (!previousMode || !authForm.value.email.trim())) {
    authForm.value.email = localStorage.getItem(LAST_LOGIN_EMAIL_KEY)?.trim() ?? ''
  }
}, { immediate: true })

if (desktop) {
  let openingControl: HTMLElement | null = null
  watch(dialog, element => {
    if (element) {
      openingControl = document.activeElement instanceof HTMLElement ? document.activeElement : null
      element.focus({ preventScroll: true })
    } else {
      openingControl?.focus({ preventScroll: true })
      openingControl = null
    }
  }, { flush: 'post' })
}

function toggleAuthMode() {
  mode.value = isLoginMode.value ? 'register' : 'login'
}

async function handleAuthSubmit() {
  const { email, password, displayName } = authForm.value
  const login = isLoginMode.value
  authLoading.value = true
  authError.value = ''

  try {
    if (!login) {
      await api.post('/auth/register', {
        email,
        password,
        display_name: displayName || email.split('@')[0]
      })
    }

    const params = new URLSearchParams({ username: login ? email.trim() : email, password })
    const { data } = await api.post('/auth/login', params)
    authStore.setToken(data.access_token)
    await authStore.fetchCurrentUser()
    if (email.trim()) localStorage.setItem(LAST_LOGIN_EMAIL_KEY, email.trim())
    mode.value = null
    if (desktop) {
      await desktop.config.setConfig({ serverUrl: getApiServerUrl(), token: authStore.token })
    }
  } catch (error: unknown) {
    authError.value = formatApiError(error, t('auth.errors.auth_failed'), t)
  } finally {
    authLoading.value = false
  }
}

function armAuthModalOverlayClose(event: PointerEvent) {
  if (event.button === 0) authModalOverlayArmed.value = true
}

function cancelAuthModalOverlayClose() {
  authModalOverlayArmed.value = false
}

function finishAuthModalOverlayClose() {
  if (!authModalOverlayArmed.value) return
  cancelAuthModalOverlayClose()
  mode.value = null
}

function closeOnEscape() {
  if (desktop) mode.value = null
}

onMounted(() => window.addEventListener('blur', cancelAuthModalOverlayClose))
onBeforeUnmount(() => window.removeEventListener('blur', cancelAuthModalOverlayClose))
</script>

<template>
  <div
    v-if="mode"
    class="modal-overlay"
    @pointerdown.self="armAuthModalOverlayClose"
    @pointerup.self="finishAuthModalOverlayClose"
    @pointerleave.self="cancelAuthModalOverlayClose"
    @pointercancel.self="cancelAuthModalOverlayClose"
  >
    <div ref="dialog" class="auth-modal glass-panel" role="dialog" :aria-labelledby="dialogId" tabindex="-1" @keydown.esc="closeOnEscape">
      <div class="auth-modal-header">
        <h2 :id="dialogId">{{ isLoginMode ? $t('portal.login_welcome') : $t('portal.register_start') }}</h2>
        <p class="auth-subtitle">{{ $t('portal.auth_subtitle') }}</p>
      </div>

      <form @submit.prevent="handleAuthSubmit" class="auth-form-content">
        <div v-if="!isLoginMode" class="form-group">
          <label :for="`${dialogId}-name`">{{ $t('portal.display_name') }}</label>
          <input :id="`${dialogId}-name`" v-model="authForm.displayName" type="text" class="modal-input" :placeholder="$t('portal.display_name')">
        </div>
        <div class="form-group">
          <label :for="`${dialogId}-email`">{{ $t('portal.email') }}</label>
          <input :id="`${dialogId}-email`" v-model="authForm.email" type="email" required class="modal-input" :placeholder="$t('portal.email_placeholder')">
        </div>
        <div class="form-group">
          <label :for="`${dialogId}-password`">{{ $t('portal.password') }}</label>
          <input :id="`${dialogId}-password`" v-model="authForm.password" type="password" required class="modal-input" :placeholder="$t('portal.password_placeholder')">
        </div>

        <div v-if="authError" class="auth-error-msg">
          {{ authError }}
        </div>

        <button type="submit" class="btn-primary auth-modal-submit" :disabled="authLoading">
          <Loader2 v-if="authLoading" class="w-4 h-4 animate-spin" />
          {{ authLoading ? $t('common.loading') : (isLoginMode ? $t('common.login') : $t('common.register')) }}
        </button>
      </form>

      <!-- 三方登录按钮区（三方优先，双入口并存）：弹窗场景为纯登录语义，已登录用户不会看到弹窗 -->
      <OAuthProviderButtons mode="login" @authorize-error="(msg: string) => (authError = msg)" />

      <div class="auth-modal-footer">
        <p>
          {{ isLoginMode ? $t('portal.no_account') : $t('portal.has_account') }}
          <a href="#" @click.prevent="toggleAuthMode">
            {{ isLoginMode ? $t('portal.switch_to_register') : $t('portal.switch_to_login') }}
          </a>
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped src="./portalPrimaryButton.css"></style>
<style scoped>
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  font-family: 'Open Sans', sans-serif;
  color: #1e3a8a;
}

.auth-modal {
  width: 100%;
  max-width: 400px;
  opacity: 1;
  transform: translateY(0);
  background: white;
  padding: 2.5rem;
  border-radius: 1.5rem;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  border: 1px solid #f1f5f9;
}

.auth-modal-header {
  text-align: center;
  margin-bottom: 2rem;
}

.auth-modal-header h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.auth-subtitle {
  font-size: 0.875rem;
  color: #64748b;
}

.auth-form-content {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #475569;
}

.modal-input {
  padding: 0.75rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.9375rem;
  transition: all 0.2s;
  font-family: inherit;
}

.modal-input:focus {
  border-color: #0ea5e9;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.1);
}

.auth-modal-submit {
  padding: 0.875rem;
  font-size: 1rem;
  margin-top: 0.5rem;
}

.auth-error-msg {
  padding: 0.75rem;
  background: #fef2f2;
  color: #ef4444;
  border-radius: 8px;
  font-size: 0.8125rem;
  text-align: left;
  white-space: pre-line;
}

.auth-modal-footer {
  margin-top: 1.5rem;
  text-align: center;
  font-size: 0.875rem;
  color: #64748b;
}

.auth-modal-footer a {
  color: #0ea5e9;
  font-weight: 600;
  text-decoration: none;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.animate-spin {
  animation: spin 1s linear infinite;
}
</style>
