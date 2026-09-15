<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { resolveOAuthTicket, completeOAuthRegister } from '@/services/oauthApi'
import { sanitizeInternalPath } from '@/composables/useOAuthFlow'
import { formatOAuthApiError, getOAuthErrorCode } from '@/utils/error'
import OAuthErrorBanner from '@/components/auth/OAuthErrorBanner.vue'

/**
 * 路径 C 补全注册页（T04 / F-08，US-1 / AC-4 / AC-5）
 * - 邮箱以用户手填为准（拍板 #6），三方 email 仅作预填默认值，用户可改
 * - 密码必填（6~128，与 UserRegister 一致）+ 确认密码
 * - 固定提示条：说明设置密码的作用（NFR-U3）
 * - E-3：中途离开给出「未完成注册」确认提示；放弃不建号不建绑定，ticket 超时自动失效
 * - E-10：email_verified=false 时 UI 标注未验证提示
 */
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const phase = ref<'loading' | 'ready' | 'done'>('loading')
const errorCode = ref<string | null>(null)
const errorMessage = ref('')

const ticket = ref('')
const providerName = ref('')
const emailVerified = ref<boolean | null>(null)

const submitting = ref(false)
const formError = ref('')
const submitted = ref(false)

const form = reactive({
  email: '',
  password: '',
  confirmPassword: '',
  displayName: '',
})

const initialSnapshot = ref('')
const isDirty = computed(() =>
  JSON.stringify({ email: form.email, password: form.password, confirmPassword: form.confirmPassword, displayName: form.displayName })
  !== initialSnapshot.value,
)

const emailFormatOk = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim()))

const validate = (): string | null => {
  if (!form.email.trim()) return t('auth.oauth.register.email_required')
  if (!emailFormatOk.value) return t('auth.errors.email_invalid')
  if (!form.password) return t('auth.oauth.register.password_required')
  if (form.password.length < 6 || form.password.length > 128) return t('auth.errors.too_short', { min: 6 })
  if (form.password !== form.confirmPassword) return t('auth.oauth.register.password_mismatch')
  return null
}

const showError = (error: unknown): void => {
  errorCode.value = getOAuthErrorCode(error)
  errorMessage.value = formatOAuthApiError(error, t('auth.oauth.errors.default'), t)
  phase.value = 'done'
}

const backToLogin = (): void => {
  void router.push('/')
}

const applyStatusLocally = async (status: string): Promise<void> => {
  // ticket 状态与本页不匹配（用户刷新 / 回退）：按状态机重新分发
  if (status === 'LOGIN_OK') {
    router.push('/workspaces')
    return
  }
  if (status === 'BIND_REQUIRED') {
    router.push({ name: 'oauthBindConfirm', query: { ticket: ticket.value } })
    return
  }
  showError('OAUTH_TICKET_INVALID')
}

const init = async (): Promise<void> => {
  const queryTicket = typeof route.query.ticket === 'string' ? route.query.ticket : ''
  if (!queryTicket) {
    showError('OAUTH_TICKET_INVALID')
    return
  }
  ticket.value = queryTicket
  try {
    // resolve 为幂等读，可重复调用（§2.1.3 备注）
    const result = await resolveOAuthTicket(queryTicket)
    if (result.status !== 'REGISTER_REQUIRED') {
      await applyStatusLocally(result.status)
      return
    }
    providerName.value = result.provider ?? ''
    emailVerified.value = result.email_verified ?? null
    // 手填优先：三方 email 只是预填默认值
    form.email = result.suggested_email ?? ''
    form.displayName = result.suggested_display_name ?? ''
    initialSnapshot.value = JSON.stringify({ email: form.email, password: form.password, confirmPassword: form.confirmPassword, displayName: form.displayName })
    phase.value = 'ready'
  } catch (error: unknown) {
    showError(error)
  }
}

const handleSubmit = async (): Promise<void> => {
  const invalid = validate()
  if (invalid) {
    formError.value = invalid
    return
  }
  submitting.value = true
  formError.value = ''
  try {
    const res = await completeOAuthRegister({
      ticket: ticket.value,
      email: form.email.trim(),
      password: form.password,
      display_name: form.displayName.trim() || form.email.trim().split('@')[0],
    })
    submitted.value = true
    authStore.setToken(res.access_token)
    await authStore.fetchCurrentUser()
    const redirect = sanitizeInternalPath(typeof route.query.redirect === 'string' ? route.query.redirect : null)
    await router.push(redirect ?? '/workspaces')
  } catch (error: unknown) {
    // 409 邮箱冲突：ticket 未消费，用户可改邮箱重试（E-1b）
    formError.value = formatOAuthApiError(error, t('auth.oauth.errors.default'), t)
  } finally {
    submitting.value = false
  }
}

/* E-3：未提交前离开需确认（路由守卫 + 刷新拦截） */
onBeforeRouteLeave(async () => {
  if (phase.value === 'ready' && isDirty.value && !submitted.value) {
    try {
      await ElMessageBox.confirm(t('auth.oauth.register.leave_confirm'), t('auth.oauth.register.leave_title'), {
        type: 'warning',
        confirmButtonText: t('auth.oauth.register.leave_stay'),
        cancelButtonText: t('auth.oauth.register.leave_go'),
      })
      return false // 用户选择留下
    } catch {
      return true // 用户确认离开
    }
  }
  return true
})

const beforeUnload = (event: BeforeUnloadEvent): void => {
  if (phase.value === 'ready' && isDirty.value && !submitted.value) {
    event.preventDefault()
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  init().finally(() => window.removeEventListener('beforeunload', beforeUnload))
})
</script>

<template>
  <div class="auth-container">
    <div class="auth-card glass-panel">
      <div class="auth-header">
        <h2>{{ t('auth.oauth.register.title') }}</h2>
        <p class="subtitle">{{ t('auth.oauth.register.subtitle', { provider: providerName }) }}</p>
      </div>

      <div v-if="phase === 'loading'" class="state-block">
        <span class="spinner" aria-hidden="true"></span>
        <p>{{ t('auth.oauth.callback.resolving') }}</p>
      </div>

      <template v-else-if="phase === 'ready'">
        <div class="tip-bar">
          <svg class="tip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4M12 8h.01" />
          </svg>
          <span>{{ t('auth.oauth.register.tip', { provider: providerName }) }}</span>
        </div>

        <form class="auth-form" @submit.prevent="handleSubmit">
          <div class="form-group">
            <label for="oauth-reg-email">{{ t('auth.oauth.register.email_label') }}</label>
            <input
              id="oauth-reg-email"
              v-model="form.email"
              type="email"
              required
              class="input-field"
              :placeholder="t('auth.oauth.register.email_placeholder')"
            >
            <p v-if="emailVerified === false" class="field-hint warn">
              {{ t('auth.oauth.register.email_unverified', { provider: providerName }) }}
            </p>
            <p class="field-hint">{{ t('auth.oauth.register.email_hint') }}</p>
          </div>

          <div class="form-group">
            <label for="oauth-reg-password">{{ t('auth.oauth.register.password_label') }}</label>
            <input
              id="oauth-reg-password"
              v-model="form.password"
              type="password"
              required
              class="input-field"
              autocomplete="new-password"
              placeholder="••••••••"
            >
          </div>

          <div class="form-group">
            <label for="oauth-reg-confirm">{{ t('auth.oauth.register.confirm_password_label') }}</label>
            <input
              id="oauth-reg-confirm"
              v-model="form.confirmPassword"
              type="password"
              required
              class="input-field"
              autocomplete="new-password"
              placeholder="••••••••"
            >
          </div>

          <div class="form-group">
            <label for="oauth-reg-name">{{ t('auth.oauth.register.display_name_label') }}</label>
            <input
              id="oauth-reg-name"
              v-model="form.displayName"
              type="text"
              class="input-field"
              :placeholder="t('auth.oauth.register.display_name_placeholder')"
            >
          </div>

          <p v-if="formError" class="error-msg">{{ formError }}</p>

          <button type="submit" class="btn-primary auth-submit" :disabled="submitting">
            {{ submitting ? t('auth.oauth.register.submitting') : t('auth.oauth.register.submit') }}
          </button>
        </form>
      </template>

      <template v-else>
        <OAuthErrorBanner :code="errorCode" :message="errorMessage">
          <template #actions>
            <button type="button" class="btn-primary" @click="backToLogin">
              {{ t('auth.oauth.actions.relogin') }}
            </button>
          </template>
        </OAuthErrorBanner>
      </template>
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
  max-width: 460px;
  padding: var(--space-8);
  margin: var(--space-4);
  background-color: rgba(255, 255, 255, 0.85);
  box-shadow: var(--shadow-lg);
}

.auth-header {
  text-align: center;
  margin-bottom: var(--space-5);
}

.auth-header h2 {
  font-size: 1.5rem;
  margin-bottom: var(--space-1);
}

.subtitle {
  color: var(--color-text-muted);
  font-size: 0.9rem;
  margin: 0;
}

.tip-bar {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-5);
  background-color: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.25);
  border-radius: var(--radius-md);
  font-size: 0.85rem;
  color: var(--color-text-body);
  line-height: 1.5;
}

.tip-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--color-primary-500);
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

.field-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-text-muted);
}

.field-hint.warn {
  color: #d97706;
}

.error-msg {
  color: var(--color-accent-rose);
  font-size: 0.875rem;
  text-align: left;
  white-space: pre-line;
  background-color: rgba(244, 63, 94, 0.1);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
}

.auth-submit {
  margin-top: var(--space-2);
  padding: 14px;
  font-size: 1rem;
}

.btn-primary {
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-primary-500);
  color: #fff;
  cursor: pointer;
  font-family: inherit;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.state-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-muted);
  padding: var(--space-6) 0;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--color-primary-200, #bfdbfe);
  border-top-color: var(--color-primary-500);
  border-radius: 50%;
  animation: oauth-spin 0.8s linear infinite;
}

@keyframes oauth-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
