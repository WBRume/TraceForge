<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useOAuthStore } from '@/stores/oauth'
import { useOAuthFlow, sanitizeInternalPath } from '@/composables/useOAuthFlow'
import { bindOAuthIdentity } from '@/services/oauthApi'
import { formatOAuthApiError, getOAuthErrorCode } from '@/utils/error'
import OAuthErrorBanner from '@/components/auth/OAuthErrorBanner.vue'
import type { OAuthResolveResult } from '@/types/oauth'

/**
 * OAuth 回调页（T04 / F-07，§3.8.1 状态机）
 * 后端 302 落地：/oauth/callback?ticket=xxx&status=xxx&client_type=web
 *           或 /oauth/callback?error=<语义化错误码>&provider=xxx
 * 流程：ticket → POST /oauth/resolve（幂等读）→ 按 status 分发：
 *   LOGIN_OK          → 存 token（URL 永不含 JWT，token 只经 resolve 兑换）→ 首页
 *   BIND_REQUIRED     → /oauth/bind-confirm（路径 B）
 *   REGISTER_REQUIRED → /oauth/register（路径 C）
 *   CONFIRM_REQUIRED  → 本页弹管理员密码确认框（POST /oauth/bind）
 *   ALREADY_BOUND / BIND_CONFLICT → 本页展示结果，引导返回
 */
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const oauthStore = useOAuthStore()
const { resolveAndDispatch } = useOAuthFlow()

type Phase = 'resolving' | 'confirm' | 'done'

const phase = ref<Phase>('resolving')
const errorCode = ref<string | null>(null)
const errorMessage = ref('')
const resultMessage = ref('')
const resultSuccess = ref(false)

/* CONFIRM_REQUIRED（管理员加绑）的密码确认框 */
const confirmVisible = ref(false)
const confirmPassword = ref('')
const confirmLoading = ref(false)
const confirmError = ref('')
const confirmAttemptsLeft = ref<number | null>(null)

let resolvedTicket: string | null = null

const providerLabel = (result: OAuthResolveResult | null): string =>
  oauthStore.providers.find(p => p.name === result?.provider)?.display_name
  ?? result?.provider_display_name
  ?? result?.provider
  ?? ''

const showError = (error: unknown): void => {
  errorCode.value = getOAuthErrorCode(error)
  errorMessage.value = formatOAuthApiError(error, t('auth.oauth.errors.default'), t)
  phase.value = 'done'
}

const backToLogin = (): void => {
  oauthStore.resetFlow()
  router.push('/')
}

const backToWorkspaces = (): void => {
  oauthStore.resetFlow()
  router.push('/workspaces')
}

const handleResolve = async (): Promise<void> => {
  const queryTicket = typeof route.query.ticket === 'string' ? route.query.ticket : ''
  const queryError = typeof route.query.error === 'string' ? route.query.error : ''
  const queryRedirect = typeof route.query.redirect_after === 'string' ? route.query.redirect_after
    : (typeof route.query.redirect === 'string' ? route.query.redirect : '')

  // 三方取消授权 / state 失效等：后端 302 带 error 码（接口 3）
  if (queryError) {
    showError(queryError)
    return
  }
  if (!queryTicket) {
    showError('OAUTH_TICKET_INVALID')
    return
  }

  resolvedTicket = queryTicket
  try {
    const result = await resolveAndDispatch(queryTicket, sanitizeInternalPath(queryRedirect) ?? undefined)

    // 加绑（intent=bind）在 resolveAndDispatch 内已完成 /bind；直接展示成功态
    const completedProvider = oauthStore.completedBindProvider
    if (completedProvider) {
      oauthStore.completedBindProvider = null
      resultSuccess.value = true
      resultMessage.value = t('auth.oauth.messages.bind_success', { provider: completedProvider })
      phase.value = 'done'
      return
    }

    // resolveAndDispatch 内部已处理 LOGIN_OK（登录）/ BIND_REQUIRED / REGISTER_REQUIRED 的跳转，
    // 执行到这里的只剩加绑相关终态
    switch (result.status) {
      case 'CONFIRM_REQUIRED':
        // 管理员账号加绑：必须二次密码确认（拍板 #8 / E-8）
        phase.value = 'confirm'
        confirmVisible.value = true
        break
      case 'ALREADY_BOUND':
        resultSuccess.value = true
        resultMessage.value = t('auth.oauth.messages.already_bound', { provider: providerLabel(result) })
        phase.value = 'done'
        break
      case 'BIND_CONFLICT':
        errorCode.value = 'OAUTH_IDENTITY_CONFLICT'
        phase.value = 'done'
        break
      default:
        break
    }
  } catch (error: unknown) {
    showError(error)
  }
}

const submitAdminConfirm = async (): Promise<void> => {
  if (!resolvedTicket || !confirmPassword.value) return
  confirmLoading.value = true
  confirmError.value = ''
  confirmAttemptsLeft.value = null
  try {
    await bindOAuthIdentity(resolvedTicket, confirmPassword.value)
    confirmVisible.value = false
    await authStore.fetchCurrentUser() // 刷新 bound_providers
    resultSuccess.value = true
    resultMessage.value = t('auth.oauth.messages.bind_success', { provider: providerLabel(oauthStore.resolveResult) })
    phase.value = 'done'
  } catch (error: unknown) {
    const axiosError = error as { response?: { data?: { attempts_left?: number } } }
    const attemptsLeft = axiosError.response?.data?.attempts_left
    if (typeof attemptsLeft === 'number' && attemptsLeft >= 0) {
      confirmAttemptsLeft.value = attemptsLeft
      confirmError.value = t('auth.oauth.errors.password_invalid') + ' ' + t('auth.oauth.bind_confirm.attempts_left', { n: attemptsLeft })
    } else {
      confirmError.value = formatOAuthApiError(error, t('auth.oauth.errors.default'), t)
    }
  } finally {
    confirmLoading.value = false
  }
}

/* Electron 桌面端：本地回环服务在主进程解析回调（T05），
   浏览器侧本页仅处理 web 回调；client_type=desktop 仅作预留标识 */
const isDesktopCallback = (): boolean => route.query.client_type === 'desktop'
void isDesktopCallback

onMounted(handleResolve)

const onBeforeUnload = (event: BeforeUnloadEvent): void => {
  if (phase.value === 'resolving' || phase.value === 'confirm') {
    event.preventDefault()
  }
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))
</script>

<template>
  <div class="auth-container">
    <div class="auth-card glass-panel">
      <div class="auth-header">
        <h2>{{ t('auth.oauth.callback.title') }}</h2>
      </div>

      <div v-if="phase === 'resolving'" class="state-block">
        <span class="spinner" aria-hidden="true"></span>
        <p>{{ t('auth.oauth.callback.resolving') }}</p>
      </div>

      <template v-else-if="phase === 'done'">
        <OAuthErrorBanner v-if="!resultSuccess" :code="errorCode" :message="errorMessage">
          <template #actions>
            <div class="banner-actions">
              <button type="button" class="btn-primary" @click="backToLogin">
                {{ t('auth.oauth.actions.relogin') }}
              </button>
              <button
                v-if="authStore.isAuthenticated"
                type="button"
                class="btn-secondary"
                @click="backToWorkspaces"
              >
                {{ t('auth.oauth.actions.back_workspaces') }}
              </button>
            </div>
          </template>
        </OAuthErrorBanner>

        <div v-else class="success-block">
          <svg class="success-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <path d="m9 11 3 3L22 4" />
          </svg>
          <p>{{ resultMessage }}</p>
          <div class="banner-actions">
            <button type="button" class="btn-primary" @click="backToWorkspaces">
              {{ t('auth.oauth.actions.back_workspaces') }}
            </button>
          </div>
        </div>
      </template>

      <el-dialog
        v-model="confirmVisible"
        :title="t('auth.oauth.bind_confirm.admin_title')"
        width="420px"
        :close-on-click-modal="false"
      >
        <p class="confirm-desc">{{ t('auth.oauth.bind_confirm.admin_desc') }}</p>
        <el-input
          v-model="confirmPassword"
          type="password"
          :placeholder="t('auth.oauth.bind_confirm.password_placeholder')"
          show-password
          autocomplete="current-password"
          @keyup.enter="submitAdminConfirm"
        />
        <p v-if="confirmError" class="confirm-error">{{ confirmError }}</p>
        <template #footer>
          <el-button @click="confirmVisible = false; backToWorkspaces()">
            {{ t('auth.oauth.bind_confirm.cancel') }}
          </el-button>
          <el-button type="primary" :loading="confirmLoading" @click="submitAdminConfirm">
            {{ t('auth.oauth.bind_confirm.submit') }}
          </el-button>
        </template>
      </el-dialog>
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
  margin-bottom: var(--space-6);
}

.auth-header h2 {
  font-size: 1.5rem;
  margin-bottom: var(--space-1);
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

.banner-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.btn-primary {
  padding: 8px 20px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-primary-500);
  color: #fff;
  font-size: 0.875rem;
  cursor: pointer;
  font-family: inherit;
}

.btn-secondary {
  padding: 8px 20px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  color: var(--color-text-body);
  font-size: 0.875rem;
  cursor: pointer;
  font-family: inherit;
}

.success-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-body);
  text-align: center;
}

.success-icon {
  width: 40px;
  height: 40px;
  color: #16a34a;
}

.confirm-desc {
  margin: 0 0 var(--space-3);
  font-size: 0.9rem;
  color: var(--color-text-body);
  line-height: 1.5;
}

.confirm-error {
  margin: var(--space-2) 0 0;
  font-size: 0.85rem;
  color: var(--color-accent-rose);
}
</style>
