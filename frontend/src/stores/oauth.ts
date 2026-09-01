/**
 * OAuth 流程状态 store（T04 / F-03）
 * 设计约束（§1.3 决策 6）：独立于 stores/auth.ts，不污染认证 store。
 * stores/auth.ts 仅新增 bound_providers 展示状态。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { listOAuthProviders } from '@/services/oauthApi'
import type { OAuthProviderInfo, OAuthResolveResult } from '@/types/oauth'

export const useOAuthStore = defineStore('oauth', () => {
  /* provider 列表（登录页按钮区数据源；为空时按钮区整体隐藏） */
  const providers = ref<OAuthProviderInfo[]>([])
  const providersLoaded = ref(false)
  const providersLoading = ref(false)

  /* 回调页 resolve 结果（跨页面传递预填信息，避免把邮箱明文放进 URL） */
  const resolveResult = ref<OAuthResolveResult | null>(null)

  /* 当前正在处理的 ticket（bind 终态 / 管理员二次确认时使用） */
  const pendingTicket = ref<string | null>(null)

  /* 最近一次「加绑成功」的 provider（供设置页 / 回调页展示成功态，由调用方读取后清空） */
  const completedBindProvider = ref<string | null>(null)

  const hasProviders = computed(() => providers.value.length > 0)

  async function loadProviders(force = false): Promise<void> {
    if (providersLoading.value) return
    if (providersLoaded.value && !force) return
    providersLoading.value = true
    try {
      const res = await listOAuthProviders()
      providers.value = res.providers ?? []
      providersLoaded.value = true
    } finally {
      providersLoading.value = false
    }
  }

  function setResolveResult(result: OAuthResolveResult | null): void {
    resolveResult.value = result
  }

  function resetFlow(): void {
    resolveResult.value = null
    pendingTicket.value = null
  }

  return {
    providers,
    providersLoaded,
    providersLoading,
    hasProviders,
    resolveResult,
    pendingTicket,
    completedBindProvider,
    loadProviders,
    setResolveResult,
    resetFlow,
  }
})
