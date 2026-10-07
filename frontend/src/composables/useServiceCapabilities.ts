import { computed, onMounted, onUnmounted, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { featureConfigApi, type Capability, type FeatureConfig, type FeatureId } from '@/services/featureConfigApi'
import { formatApiError } from '@/utils/error'

export const serviceFeatures: FeatureId[] = ['speech', 'search', 'diagnosis', 'oauth', 'agent']

// 模块级单例缓存：跨路由导航共享探测状态，避免重复缓慢探测
const sharedConfigs = shallowRef<FeatureConfig[]>([])
const sharedCapabilities = shallowRef<Capability[]>([])
const sharedLoading = shallowRef(false)
const sharedError = shallowRef('')
let lastFetchedAt = 0
let activeRequestPromise: Promise<void> | null = null
let activeSubscribers = 0
let globalTimer: number | undefined

export function useServiceCapabilities() {
  const { t } = useI18n()

  const readyCount = computed(() => sharedCapabilities.value.filter(item => item.status === 'READY').length)
  const services = computed(() => serviceFeatures.map(feature => ({
    feature,
    title: t('feature_config.features.' + feature),
    config: sharedConfigs.value.find(item => item.feature === feature),
    capability: sharedCapabilities.value.find(item => item.feature === feature),
  })))

  const refresh = async (reloadConfigs = false, force = false): Promise<void> => {
    // 缓存有效性检查：已有探测结果且在 60 秒有效期内，非强制请求直接复用内存数据
    const hasCache = sharedCapabilities.value.length > 0 && sharedConfigs.value.length > 0
    const isFresh = Date.now() - lastFetchedAt < 60000
    if (!force && hasCache && isFresh && !reloadConfigs) {
      return
    }

    if (activeRequestPromise) {
      return activeRequestPromise
    }

    sharedLoading.value = true
    sharedError.value = ''

    activeRequestPromise = (async () => {
      try {
        const [configuration, status] = await Promise.allSettled([
          reloadConfigs || !sharedConfigs.value.length ? featureConfigApi.configs() : Promise.resolve(null),
          featureConfigApi.capabilities(),
        ])

        if (configuration.status === 'fulfilled') {
          if (configuration.value) sharedConfigs.value = configuration.value.data.items
        } else {
          sharedError.value = formatApiError(configuration.reason, t('feature_config.load_failed'), t)
        }

        if (status.status === 'fulfilled') {
          sharedCapabilities.value = status.value.data.items
          lastFetchedAt = Date.now()
        } else {
          sharedError.value = formatApiError(status.reason, t('feature_config.load_failed'), t)
          sharedCapabilities.value = serviceFeatures.map(feature => ({
            feature,
            title: t('feature_config.features.' + feature),
            status: 'DEGRADED',
            mode: 'unavailable',
            explanation: t('feature_config.load_failed'),
            guidance: t('feature_config.refresh'),
            facts: {},
            checked_at: '',
          }))
        }
      } finally {
        sharedLoading.value = false
        activeRequestPromise = null
      }
    })()

    return activeRequestPromise
  }

  const applySaved = (config: FeatureConfig) => {
    sharedConfigs.value = sharedConfigs.value.map(item => item.feature === config.feature ? config : item)
    // 保存配置后强制重新探测刷新
    void refresh(false, true)
  }

  onMounted(() => {
    activeSubscribers++
    // 挂载时如果无缓存或已过期则探测；若已有有效缓存则秒开复用
    void refresh(false, false)

    if (!globalTimer) {
      globalTimer = window.setInterval(() => {
        if (!document.hidden && !sharedLoading.value && activeSubscribers > 0) {
          void refresh(false, true)
        }
      }, 30000)
    }
  })

  onUnmounted(() => {
    activeSubscribers = Math.max(0, activeSubscribers - 1)
    if (activeSubscribers === 0 && globalTimer) {
      window.clearInterval(globalTimer)
      globalTimer = undefined
    }
  })

  return {
    services,
    loading: sharedLoading,
    error: sharedError,
    readyCount,
    refresh: (force = true) => refresh(false, force),
    applySaved,
  }
}
