<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { getOAuthErrorKey } from '@/utils/error'

/**
 * OAuth 错误提示横幅（T04 / F-06）
 * §3.8.3：后端 code / error → 统一文案映射；
 * state_expired / state_invalid / code_invalid 三者文案必须完全相同（E-4d）。
 */
const props = defineProps<{
  /** 后端语义化错误码（如 access_denied）或 API 错误码（如 OAUTH_TICKET_EXPIRED） */
  code?: string | null
  /** 覆盖映射文案的直接消息 */
  message?: string
}>()

const { t } = useI18n()

const mappedMessage = computed<string | null>(() => {
  const key = getOAuthErrorKey(props.code)
  return key ? t(key) : null
})

const displayMessage = computed<string>(() => props.message || mappedMessage.value || t('auth.oauth.errors.default'))
</script>

<template>
  <div v-if="displayMessage" class="oauth-error-banner" role="alert">
    <svg class="banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v4M12 16h.01" />
    </svg>
    <div class="banner-body">
      <p class="banner-message">{{ displayMessage }}</p>
      <slot name="actions"></slot>
    </div>
  </div>
</template>

<style scoped>
.oauth-error-banner {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background-color: rgba(244, 63, 94, 0.1);
  border: 1px solid rgba(244, 63, 94, 0.35);
  border-radius: var(--radius-md);
  color: var(--color-accent-rose);
}

.banner-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  margin-top: 2px;
}

.banner-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.banner-message {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.5;
  white-space: pre-line;
}
</style>
