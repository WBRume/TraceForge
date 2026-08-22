import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

export type AgentBackendOption = {
  value: string
  label: string
  supports_resume: boolean
  preferred_mode: string
}

export type AgentBackendPayload = {
  agent_backend: string | null
  effective_agent_backend: string
  default_agent_backend: string
  options: AgentBackendOption[]
}

/**
 * 工作区级底层 Agent 配置。
 * agent_backend 为空表示跟随服务端全局默认（.env AGENT_BACKEND）。
 */
export function useAgentBackendSettings() {
  const route = useRoute()
  const { t } = useI18n()

  const workspaceId = computed(() => String(route.params.wsId || ''))

  const payload = ref<AgentBackendPayload | null>(null)
  const selected = ref<string>('')
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')
  const success = ref('')

  const options = computed(() => payload.value?.options || [])
  const defaultBackend = computed(() => payload.value?.default_agent_backend || '')
  const effectiveBackend = computed(() => payload.value?.effective_agent_backend || '')
  const isOverridden = computed(() => Boolean(payload.value?.agent_backend))
  const supportsResume = computed(() => (
    options.value.find((option) => option.value === selected.value)?.supports_resume ?? true
  ))

  const clearMessage = () => {
    error.value = ''
    success.value = ''
  }

  const load = async () => {
    if (!workspaceId.value) return
    loading.value = true
    clearMessage()
    try {
      const res = await api.get(`/workspaces/${workspaceId.value}/agent-backends`)
      payload.value = res.data
      selected.value = res.data.agent_backend || res.data.effective_agent_backend || ''
    } catch (err) {
      error.value = formatApiError(err, t('settings.agent.load_failed'), t)
    } finally {
      loading.value = false
    }
  }

  const save = async () => {
    if (!workspaceId.value || !selected.value) return
    saving.value = true
    clearMessage()
    try {
      const override = selected.value === defaultBackend.value ? null : selected.value
      const res = await api.put(`/workspaces/${workspaceId.value}/agent-backend`, {
        agent_backend: override,
      })
      payload.value = res.data
      selected.value = res.data.agent_backend || res.data.effective_agent_backend || ''
      success.value = t('settings.agent.save_success')
    } catch (err) {
      error.value = formatApiError(err, t('settings.agent.save_failed'), t)
    } finally {
      saving.value = false
    }
  }

  watch(workspaceId, (next, prev) => {
    if (next && next !== prev) void load()
  }, { immediate: true })

  return {
    payload,
    options,
    selected,
    defaultBackend,
    effectiveBackend,
    isOverridden,
    supportsResume,
    loading,
    saving,
    error,
    success,
    load,
    save,
  }
}
