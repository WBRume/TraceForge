<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { resolveOAuthTicket, confirmOAuthBind } from '@/services/oauthApi'
import { formatOAuthApiError, getOAuthErrorCode } from '@/utils/error'
import OAuthErrorBanner from '@/components/auth/OAuthErrorBanner.vue'

/**
 * 路径 B 确认绑定页（T04 / F-09，🔴 安全红线 AC-S2 / AC-S7）
 * - 仅展示脱敏邮箱（email_masked，如 z***@example.com），resolve 是未认证端点
 * - 密码验证通过 → 绑定该三方身份并签发 token 登录
 * - 🔴 密码错误与账号不存在返回完全相同的响应（不可区分）
 * - E-18：连续失败 5 次作废 ticket 并冷却 15 分钟；后端附带 attempts_left 时展示剩余次数
 */
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const phase = ref<'loading' | 'ready' | 'done'>('loading')
const errorCode = ref<string | null>(null)
const errorMessage = ref('')

const ticket = ref('')
const emailMasked = ref('')
const providerName = ref('')
const emailVerified = ref<boolean | null>(null)

const password = ref('')
const submitting = ref(false)
const formError = ref('')
const attemptsLeft = ref<number | null>(null)

const backToLogin = (): void => {
  void router.push('/')
}

const applyStatusLocally = async (status: string): Promise<void> => {
  if (status === 'LOGIN_OK') {
    router.push('/workspaces')
    return
  }
  if (status === 'REGISTER_REQUIRED') {
    router.push({ name: 'oauthRegister', query: { ticket: ticket.value } })
    return
  }
  showError('OAUTH_TICKET_INVALID')
}

const showError = (error: unknown): void => {
  errorCode.value = getOAuthErrorCode(error)
  errorMessage.value = formatOAuthApiError(error, t('auth.oauth.errors.default'), t)
  phase.value = 'done'
}

const init = async (): Promise<void> => {
  const queryTicket = typeof route.query.ticket === 'string' ? route.query.ticket : ''
  if (!queryTicket) {
    showError('OAUTH_TICKET_INVALID')
    return
  }
  ticket.value = queryTicket
  try {
    const result = await resolveOAuthTicket(queryTicket)
    if (result.status !== 'BIND_REQUIRED') {
      await applyStatusLocally(result.status)
      return
    }
    emailMasked.value = result.email_masked ?? ''
    providerName.value = result.provider ?? ''
    emailVerified.value = result.email_verified ?? null
    phase.value = 'ready'
  } catch (error: unknown) {
    showError(error)
  }
}

const handleSubmit = async (): Promise<void> => {
  if (!password.value) {
    formError.value = t('auth.oauth.bind_confirm.password_required')
    return
  }
  submitting.value = true
  formError.value = ''
  attemptsLeft.value = null
  try {
    const res = await confirmOAuthBind(ticket.value, password.value)
    authStore.setToken(res.access_token)
    await authStore.fetchCurrentUser()
    await router.push('/workspaces')
  } catch (error: unknown) {
    const axiosError = error as { response?: { data?: { attempts_left?: number } } }
    const left = axiosError.response?.data?.attempts_left
    if (typeof left === 'number' && left >= 0) {
      attemptsLeft.value = left
      formError.value = formatOAuthApiError(error, t('auth.oauth.errors.password_invalid'), t)
        + ' ' + t('auth.oauth.bind_confirm.attempts_left', { n: left })
    } else {
      // 401（密码错误/账号不存在，同一响应）/ 423（锁定）/ 410（过期）均走统一文案映射
      formError.value = formatOAuthApiError(error, t('auth.oauth.errors.default'), t)
      const code = getOAuthErrorCode(error)
      if (code === 'OAUTH_TICKET_LOCKED' || code === 'OAUTH_TICKET_EXPIRED') {
        phase.value = 'done'
        errorCode.value = code
        errorMessage.value = formError.value
        formError.value = ''
      }
    }
  } finally {
    submitting.value = false
  }
}

onMounted(init)
</script>

<template>
  <div class="auth-container">
    <div class="auth-card glass-panel">
      <div class="auth-header">
        <h2>{{ t('auth.oauth.bind_confirm.title') }}</h2>
      </div>

      <div v-if="phase === 'loading'" class="state-block">
        <span class="spinner" aria-hidden="true"></span>
        <p>{{ t('auth.oauth.callback.resolving') }}</p>
      </div>

      <template v-else-if="phase === 'ready'">
        <div class="bind-info">
          <p class="bind-desc">{{ t('auth.oauth.bind_confirm.description', { email: emailMasked, provider: providerName }) }}</p>
          <p v-if="emailVerified === false" class="field-hint warn">
            {{ t('auth.oauth.register.email_unverified', { provider: providerName }) }}
          </p>
        </div>

        <form class="auth-form" @submit.prevent="handleSubmit">
          <div class="form-group">
            <label for="oauth-bind-email">{{ t('auth.oauth.bind_confirm.email_label') }}</label>
            <input id="oauth-bind-email" type="text" class="input-field" :value="emailMasked" disabled>
          </div>

          <div class="form-group">
            <label for="oauth-bind-password">{{ t('auth.oauth.bind_confirm.password_label') }}</label>
            <input
              id="oauth-bind-password"
              v-model="password"
              type="password"
              required
              class="input-field"
              autocomplete="current-password"
              :placeholder="t('auth.oauth.bind_confirm.password_placeholder')"
            >
          </div>

          <p v-if="formError" class="error-msg">{{ formError }}</p>

          <div class="action-row">
            <button type="button" class="btn-secondary" :disabled="submitting" @click="backToLogin">
              {{ t('auth.oauth.bind_confirm.cancel') }}
            </button>
            <button type="submit" class="btn-primary auth-submit" :disabled="submitting">
              {{ submitting ? t('auth.oauth.bind_confirm.submitting') : t('auth.oauth.bind_confirm.submit') }}
            </button>
          </div>
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

.bind-info {
  margin-bottom: var(--space-5);
}

.bind-desc {
  margin: 0 0 var(--space-2);
  font-size: 0.92rem;
  color: var(--color-text-body);
  line-height: 1.6;
}

.field-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-text-muted);
}

.field-hint.warn {
  color: #d97706;
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
  font-family: inherit;
  background: var(--color-surface-white);
}

.input-field:disabled {
  background: #F8FAFC;
  color: var(--color-text-muted);
}

.input-field:focus {
  border-color: var(--color-primary-500);
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
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

.action-row {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.action-row .btn-secondary {
  flex: 1;
}

.action-row .auth-submit {
  flex: 2;
  margin-top: 0;
}

.btn-primary {
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-primary-500);
  color: #fff;
  cursor: pointer;
  font-family: inherit;
  padding: 12px;
  font-size: 1rem;
}

.btn-secondary {
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  color: var(--color-text-body);
  cursor: pointer;
  font-family: inherit;
  padding: 12px;
  font-size: 1rem;
}

.btn-primary:disabled,
.btn-secondary:disabled {
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
