<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useOAuthStore } from '@/stores/oauth'
import { useOAuthFlow } from '@/composables/useOAuthFlow'
import { formatOAuthApiError } from '@/utils/error'
import type { OAuthIntent, OAuthProviderInfo } from '@/types/oauth'

/**
 * 三方登录/绑定按钮区（T04 / F-05）
 * - 按 GET /auth/oauth/providers 返回动态渲染（NFR-M2：未启用的 provider 不会出现）
 * - providers 为空时整个按钮区自动隐藏（v-if="hasProviders"）
 * - E-14：已登录状态下按钮语义自动切为「绑定」（intent=bind）
 */
const props = defineProps<{
  /** 不传时按登录态自动判定（E-14） */
  mode?: OAuthIntent
  /** 授权完成后落地的站内路由 */
  redirectAfter?: string
}>()

const emit = defineEmits<{
  (e: 'authorize-error', message: string): void
}>()

const { t } = useI18n()
const authStore = useAuthStore()
const oauthStore = useOAuthStore()
const { startAuthorize } = useOAuthFlow()

const pendingProvider = ref<string | null>(null)

const effectiveMode = computed<OAuthIntent>(() => props.mode ?? (authStore.isAuthenticated ? 'bind' : 'login'))
const hasProviders = computed(() => oauthStore.hasProviders)

const buttonLabel = (provider: OAuthProviderInfo): string =>
  effectiveMode.value === 'bind'
    ? t('auth.oauth.bind_with', { provider: provider.display_name })
    : t('auth.oauth.login_with', { provider: provider.display_name })

const handleAuthorize = async (provider: OAuthProviderInfo): Promise<void> => {
  if (pendingProvider.value) return
  pendingProvider.value = provider.name
  try {
    await startAuthorize(provider.name, {
      intent: effectiveMode.value,
      redirectAfter: props.redirectAfter,
    })
  } catch (error: unknown) {
    emit('authorize-error', formatOAuthApiError(error, t('auth.oauth.errors.default'), t))
  } finally {
    pendingProvider.value = null
  }
}

onMounted(() => {
  oauthStore.loadProviders().catch(() => {
    // provider 列表加载失败不阻塞邮箱密码登录，仅隐藏按钮区
    oauthStore.providers = []
  })
})
</script>

<template>
  <div v-if="hasProviders" class="oauth-provider-buttons">
    <div class="oauth-divider">
      <span class="divider-line"></span>
      <span class="divider-text">{{ t('auth.oauth.divider') }}</span>
      <span class="divider-line"></span>
    </div>

    <div class="provider-list">
      <button
        v-for="provider in oauthStore.providers"
        :key="provider.name"
        type="button"
        class="provider-btn"
        :disabled="pendingProvider !== null"
        @click="handleAuthorize(provider)"
      >
        <span v-if="pendingProvider === provider.name" class="provider-spinner" aria-hidden="true"></span>
        <!-- github 内联 SVG（§5.2：不新增图标依赖） -->
        <svg
          v-else-if="provider.icon_key === 'github'"
          class="provider-icon"
          viewBox="0 0 16 16"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
        </svg>
        <svg v-else class="provider-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <span>{{ buttonLabel(provider) }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.oauth-provider-buttons {
  margin-top: var(--space-4);
}

.oauth-divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.divider-line {
  flex: 1;
  height: 1px;
  background: #E2E8F0;
}

.divider-text {
  font-size: 0.8rem;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.provider-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.provider-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  width: 100%;
  padding: 11px 16px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  font-size: 0.95rem;
  color: var(--color-text-body);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: inherit;
}

.provider-btn:hover:not(:disabled) {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.provider-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.provider-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.provider-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-primary-200, #bfdbfe);
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
