<script setup lang="ts">
/**
 * 设置页 → 已连接账号（T05 / F-05 Settings 侧）
 * - 列出当前用户已绑定的三方账号（GET /auth/oauth/identities）
 * - 每个绑定项提供「解绑」操作（DELETE /auth/oauth/identities/{id}）
 * - 「关联其他账号」按可选 provider（GET /auth/oauth/identities 返回的 available_providers）
 *   复用 useOAuthFlow.startAuthorize（intent=bind），与登录共用同一套状态机
 * 加载 / 空 / 错误态齐备，文案走 i18n。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Link2, Loader2, Unlink } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useOAuthStore } from '@/stores/oauth'
import { useOAuthFlow } from '@/composables/useOAuthFlow'
import { isElectron } from '@/utils/runtime'
import { formatApiError, formatOAuthApiError } from '@/utils/error'
import {
  bindOAuthIdentity,
  listOAuthIdentities,
  unbindOAuthIdentity,
} from '@/services/oauthApi'
import type { OAuthIdentity } from '@/types/oauth'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'

const { t } = useI18n()
const authStore = useAuthStore()
const oauthStore = useOAuthStore()
const { startAuthorize } = useOAuthFlow()

const identities = ref<OAuthIdentity[]>([])
const availableProviders = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const errorMessage = ref('')
const successMessage = ref('')

const linkingProvider = ref<string | null>(null)
const unbindingId = ref<string | null>(null)
const unbindTarget = ref<OAuthIdentity | null>(null)

/* 管理员加绑二次密码确认（CONFIRM_REQUIRED） */
const showAdminDialog = ref(false)
const adminTicket = ref<string | null>(null)
const adminProvider = ref('')
const adminPassword = ref('')
const adminLoading = ref(false)
const adminError = ref('')

const isDesktop = isElectron()

const linkedProviderSet = computed(() => new Set(identities.value.map(i => i.provider)))

const providerDisplayName = (name: string): string => {
  const info = oauthStore.providers.find(p => p.name === name)
  return info?.display_name ?? name
}

const formatBoundAt = (value?: string): string => {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

const refresh = async (): Promise<void> => {
  loading.value = true
  error.value = ''
  try {
    const res = await listOAuthIdentities()
    identities.value = res.identities ?? []
    availableProviders.value = res.available_providers ?? []
    await authStore.fetchCurrentUser()
  } catch (e: unknown) {
    error.value = formatApiError(e, t('settings.connected_accounts.load_failed'), t)
  } finally {
    loading.value = false
  }
}

const linkProvider = async (providerName: string): Promise<void> => {
  if (linkingProvider.value) return
  linkingProvider.value = providerName
  errorMessage.value = ''
  try {
    if (isDesktop) {
      const result = await startAuthorize(providerName, { intent: 'bind' })
      if (oauthStore.completedBindProvider) {
        successMessage.value = t('settings.connected_accounts.link_success', {
          provider: oauthStore.completedBindProvider,
        })
        oauthStore.completedBindProvider = null
        await refresh()
      } else if (oauthStore.pendingTicket && result?.status === 'CONFIRM_REQUIRED') {
        adminTicket.value = oauthStore.pendingTicket
        adminProvider.value = result.provider ?? providerName
        showAdminDialog.value = true
      } else if (result?.status === 'ALREADY_BOUND' || result?.status === 'BIND_CONFLICT') {
        successMessage.value = t('settings.connected_accounts.already_bound', { provider: providerName })
        oauthStore.pendingTicket = null
        await refresh()
      }
    } else {
      // web：整页跳转到系统浏览器授权，完成后由 OAuthCallbackView 处理绑定
      await startAuthorize(providerName, { intent: 'bind' })
    }
  } catch (e: unknown) {
    errorMessage.value = formatOAuthApiError(
      e,
      t('settings.connected_accounts.link_error', { message: '' }),
      t,
    ).trim()
  } finally {
    linkingProvider.value = null
  }
}

const confirmAdminBind = async (): Promise<void> => {
  if (!adminTicket.value || !adminPassword.value) return
  adminLoading.value = true
  adminError.value = ''
  try {
    await bindOAuthIdentity(adminTicket.value, adminPassword.value)
    await authStore.fetchCurrentUser()
    successMessage.value = t('settings.connected_accounts.link_success', { provider: adminProvider.value })
    showAdminDialog.value = false
    adminTicket.value = null
    adminPassword.value = ''
    oauthStore.pendingTicket = null
    await refresh()
  } catch (e: unknown) {
    const axiosError = e as { response?: { data?: { attempts_left?: number } } }
    const attemptsLeft = axiosError.response?.data?.attempts_left
    if (typeof attemptsLeft === 'number' && attemptsLeft >= 0) {
      adminError.value =
        t('auth.oauth.errors.password_invalid') +
        ' ' +
        t('auth.oauth.bind_confirm.attempts_left', { n: attemptsLeft })
    } else {
      adminError.value = formatOAuthApiError(e, t('settings.connected_accounts.link_error', { message: '' }), t)
    }
  } finally {
    adminLoading.value = false
  }
}

const askUnbind = (identity: OAuthIdentity): void => {
  unbindTarget.value = identity
}

const closeUnbind = (): void => {
  if (unbindingId.value) return
  unbindTarget.value = null
}

const confirmUnbind = async (): Promise<void> => {
  if (!unbindTarget.value) return
  unbindingId.value = unbindTarget.value.id
  errorMessage.value = ''
  try {
    await unbindOAuthIdentity(unbindTarget.value.id)
    successMessage.value = t('settings.connected_accounts.unbind_success', {
      provider: unbindTarget.value.provider_display_name,
    })
    unbindTarget.value = null
    await refresh()
  } catch (e: unknown) {
    errorMessage.value = formatOAuthApiError(
      e,
      t('settings.connected_accounts.unbind_failed', { provider: '', message: '' }),
      t,
    )
  } finally {
    unbindingId.value = null
  }
}

onMounted(async () => {
  await oauthStore.loadProviders().catch(() => {
    oauthStore.providers = []
  })
  await refresh()
})
</script>

<template>
  <section class="settings-section">
    <div class="section-header">
      <div class="icon-circle">
        <Link2 class="w-6 h-6" />
      </div>
      <div class="section-title-group">
        <h2>{{ $t('settings.connected_accounts.title') }}</h2>
        <p>{{ $t('settings.connected_accounts.subtitle') }}</p>
      </div>
    </div>

    <div v-if="successMessage" class="banner banner-success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="banner banner-error">{{ errorMessage }}</div>

    <!-- 加载态 -->
    <div v-if="loading" class="state-block">
      <Loader2 class="spin w-5 h-5" />
      <span>{{ $t('settings.connected_accounts.loading') }}</span>
    </div>

    <!-- 错误态 -->
    <div v-else-if="error" class="state-block">
      <span class="error-text">{{ error }}</span>
      <button type="button" class="text-btn" @click="refresh">{{ $t('settings.connected_accounts.retry') }}</button>
    </div>

    <template v-else>
      <!-- 已绑定账号 -->
      <div class="block">
        <h3 class="block-title">{{ $t('settings.connected_accounts.bound_title') }}</h3>

        <div v-if="identities.length === 0" class="empty-state">
          {{ $t('settings.connected_accounts.bound_empty') }}
        </div>

        <ul v-else class="identity-list">
          <li v-for="identity in identities" :key="identity.id" class="identity-card">
            <span class="provider-badge">{{ identity.provider_display_name }}</span>
            <div class="identity-meta">
              <span class="identity-email">{{ identity.provider_email }}</span>
              <span v-if="identity.created_at" class="identity-date">
                {{ $t('settings.connected_accounts.bound_at', { date: formatBoundAt(identity.created_at) }) }}
              </span>
            </div>
            <button
              type="button"
              class="unbind-btn"
              :disabled="unbindingId === identity.id"
              @click="askUnbind(identity)"
            >
              <Unlink v-if="unbindingId !== identity.id" class="w-4 h-4" />
              <Loader2 v-else class="spin w-4 h-4" />
              {{ $t('settings.connected_accounts.unbind') }}
            </button>
          </li>
        </ul>
      </div>

      <!-- 关联其他账号 -->
      <div class="block">
        <h3 class="block-title">{{ $t('settings.connected_accounts.link_title') }}</h3>
        <p class="block-desc">{{ $t('settings.connected_accounts.link_desc') }}</p>

        <div v-if="availableProviders.length === 0" class="empty-state">
          {{ $t('settings.connected_accounts.no_providers') }}
        </div>

        <div v-else class="provider-grid">
          <button
            v-for="provider in availableProviders"
            :key="provider"
            type="button"
            class="provider-link-btn"
            :disabled="linkingProvider !== null"
            @click="linkProvider(provider)"
          >
            <Loader2 v-if="linkingProvider === provider" class="spin w-4 h-4" />
            <span v-else class="provider-link-icon">＋</span>
            <span>
              {{ $t('settings.connected_accounts.link_with', { provider: providerDisplayName(provider) }) }}
              <span v-if="linkedProviderSet.has(provider)" class="linked-tag">
                {{ $t('settings.connected_accounts.linked_tag') }}
              </span>
            </span>
          </button>
        </div>
      </div>
    </template>

    <!-- 解绑确认 -->
    <ConfirmActionModal
      :show="Boolean(unbindTarget)"
      :title="$t('settings.connected_accounts.unbind_confirm_title', { provider: unbindTarget?.provider_display_name || '' })"
      :message="$t('settings.connected_accounts.unbind_confirm_message', { provider: unbindTarget?.provider_display_name || '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('settings.connected_accounts.unbind')"
      tone="danger"
      :loading="Boolean(unbindingId)"
      @cancel="closeUnbind"
      @confirm="confirmUnbind"
    />

    <!-- 管理员加绑二次密码确认 -->
    <el-dialog
      v-model="showAdminDialog"
      :title="$t('settings.connected_accounts.admin_bind_title')"
      width="420px"
      :close-on-click-modal="false"
    >
      <p class="confirm-desc">{{ $t('settings.connected_accounts.admin_bind_desc') }}</p>
      <el-input
        v-model="adminPassword"
        type="password"
        :placeholder="$t('settings.connected_accounts.admin_bind_password')"
        show-password
        autocomplete="current-password"
        @keyup.enter="confirmAdminBind"
      />
      <p v-if="adminError" class="confirm-error">{{ adminError }}</p>
      <template #footer>
        <el-button @click="showAdminDialog = false">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="adminLoading" @click="confirmAdminBind">
          {{ $t('settings.connected_accounts.admin_bind_submit') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>
<style scoped>
.block {
  margin-top: var(--space-6, 1.5rem);
}

.block-title {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0 0 0.75rem;
  color: var(--color-text-body, #0f172a);
}

.block-desc {
  font-size: 0.875rem;
  color: var(--color-text-muted, #64748b);
  margin: 0 0 1rem;
}

.banner {
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  border-radius: 0.75rem;
  font-size: 0.875rem;
}

.banner-success {
  background: rgba(22, 163, 74, 0.1);
  color: #15803d;
  border: 1px solid rgba(22, 163, 74, 0.25);
}

.banner-error {
  background: rgba(225, 29, 72, 0.08);
  color: #be123c;
  border: 1px solid rgba(225, 29, 72, 0.2);
}

.state-block {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1.5rem 0;
  color: var(--color-text-muted, #64748b);
  font-size: 0.9rem;
}

.error-text {
  color: #be123c;
}

.text-btn {
  border: none;
  background: transparent;
  color: #0ea5e9;
  cursor: pointer;
  font-size: 0.875rem;
}

.empty-state {
  padding: 1rem 0;
  color: var(--color-text-muted, #64748b);
  font-size: 0.9rem;
}

.identity-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.identity-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.875rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.875rem;
  background: var(--color-surface-white, #fff);
}

.provider-badge {
  font-weight: 600;
  font-size: 0.875rem;
  padding: 0.25rem 0.625rem;
  border-radius: 0.5rem;
  background: rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
  white-space: nowrap;
}

.identity-meta {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  flex: 1;
  min-width: 0;
}

.identity-email {
  font-size: 0.9rem;
  color: var(--color-text-body, #0f172a);
}

.identity-date {
  font-size: 0.75rem;
  color: var(--color-text-muted, #64748b);
}

.unbind-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.875rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.625rem;
  background: var(--color-surface-white, #fff);
  color: #be123c;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.unbind-btn:hover:not(:disabled) {
  border-color: #be123c;
  background: rgba(225, 29, 72, 0.06);
}

.unbind-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.provider-grid {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.provider-link-btn {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: var(--color-surface-white, #fff);
  font-size: 0.95rem;
  color: var(--color-text-body, #0f172a);
  cursor: pointer;
  transition: all 0.2s;
  font-family: inherit;
}

.provider-link-btn:hover:not(:disabled) {
  border-color: var(--color-primary-500, #0ea5e9);
  background: rgba(14, 165, 233, 0.05);
}

.provider-link-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.provider-link-icon {
  font-size: 1.1rem;
  color: #0ea5e9;
}

.linked-tag {
  margin-left: 0.5rem;
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(22, 163, 74, 0.12);
  color: #15803d;
}

.confirm-desc {
  margin: 0 0 0.75rem;
  font-size: 0.9rem;
  color: var(--color-text-body, #0f172a);
  line-height: 1.5;
}

.confirm-error {
  margin: 0.5rem 0 0;
  font-size: 0.85rem;
  color: #be123c;
}

.spin {
  animation: ca-spin 0.8s linear infinite;
}

@keyframes ca-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
