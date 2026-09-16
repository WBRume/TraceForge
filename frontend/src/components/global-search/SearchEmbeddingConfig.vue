<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { BrainCircuit, RefreshCw } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

interface EmbeddingProfile {
  id: number
  revision: number
  endpoint: string
  model_id: string
  status: string
  dimension?: number | null
  has_api_key?: boolean
}

interface SearchTarget {
  target_id: string
  status: string
  verified: boolean
}

const { t } = useI18n()
const profile = shallowRef<EmbeddingProfile | null>(null)
const endpoint = shallowRef('https://api.siliconflow.cn/v1/embeddings')
const model = shallowRef('BAAI/bge-m3')
const key = shallowRef('')
const clearKey = shallowRef(false)
const busy = shallowRef(false)
const targets = shallowRef<SearchTarget[]>([])

const load = async () => {
  const { data } = await api.get('/admin/search/embedding')
  targets.value = (data.targets || []) as SearchTarget[]
  profile.value = (data.profiles?.[0] || null) as EmbeddingProfile | null
  if (profile.value) {
    endpoint.value = profile.value.endpoint
    model.value = profile.value.model_id
  }
  key.value = ''
  clearKey.value = false
}

const perform = async (action: () => Promise<unknown>) => {
  busy.value = true
  try {
    await action()
    await load()
    ElMessage.success(t('system_config.embedding_operation_success'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('system_config.embedding_operation_failed'), t))
  } finally {
    busy.value = false
  }
}

const save = () =>
  perform(() =>
    api.put('/admin/search/embedding', {
      id: profile.value?.id,
      revision: profile.value?.revision || 0,
      endpoint: endpoint.value,
      model_id: model.value,
      ...(key.value ? { api_key: key.value } : {}),
      clear_api_key: clearKey.value,
    }),
  )

const refreshStatus = () => perform(async () => {})

onMounted(() => {
  void load().catch(() => ElMessage.error(t('system_config.embedding_load_failed')))
})
</script>

<template>
  <div class="mgmt-card">
    <div class="sys-config-row">
      <div class="sys-config-info">
        <h3 class="sys-config-name">
          <BrainCircuit class="w-4 h-4" />
          {{ $t('system_config.embedding_title') }}
        </h3>
        <p class="mgmt-hint">{{ $t('system_config.embedding_desc') }}</p>
      </div>
    </div>

    <div class="sys-config-field">
      <label for="embedding-endpoint">{{ $t('system_config.embedding_endpoint_label') }}</label>
      <input
        id="embedding-endpoint"
        v-model="endpoint"
        type="text"
        class="mgmt-input"
        :disabled="busy"
      />
    </div>

    <div class="sys-config-field">
      <label for="embedding-model">{{ $t('system_config.embedding_model_label') }}</label>
      <input
        id="embedding-model"
        v-model="model"
        type="text"
        class="mgmt-input"
        :disabled="busy"
      />
    </div>

    <div class="sys-config-field">
      <label for="embedding-key">{{ $t('system_config.embedding_api_key_label') }}</label>
      <input
        id="embedding-key"
        v-model="key"
        type="password"
        class="mgmt-input"
        autocomplete="new-password"
        :disabled="busy || clearKey"
        :placeholder="profile?.has_api_key
          ? $t('system_config.embedding_api_key_keep')
          : $t('system_config.embedding_api_key_placeholder')"
      />
      <label class="sys-config-checkbox">
        <input v-model="clearKey" type="checkbox" :disabled="busy" />
        <span>{{ $t('system_config.embedding_clear_key') }}</span>
      </label>
    </div>

    <div class="sys-config-actions">
      <button class="btn-primary" :disabled="busy" @click="save">
        {{ $t('system_config.embedding_save') }}
      </button>
      <button
        class="btn-secondary"
        :disabled="busy || !profile || !!key || endpoint !== profile.endpoint || model !== profile.model_id"
        @click="perform(() => api.post(`/admin/search/embedding/${profile?.id}/test`))"
      >
        {{ $t('system_config.embedding_test') }}
      </button>
      <button
        class="btn-secondary"
        :disabled="busy || !profile?.dimension"
        @click="perform(() => api.post(`/admin/search/embedding/${profile?.id}/build`))"
      >
        {{ $t('system_config.embedding_build') }}
      </button>
    </div>

    <div v-if="profile" class="sys-config-status">
      <span class="mgmt-status-pill blue">{{ profile.status }}</span>
      <span>
        {{ $t('system_config.embedding_dimension') }}：{{ profile.dimension || $t('system_config.embedding_dimension_unknown') }}
      </span>
    </div>

    <div v-if="targets.length > 0" class="sys-config-targets">
      <div v-for="target in targets" :key="target.target_id" class="sys-config-target-row">
        <div class="sys-config-target-meta">
          <span class="mgmt-status-pill" :class="target.status === 'active' ? 'green' : 'gray'">
            {{ target.status }}
          </span>
          <span>{{ $t('system_config.embedding_rrf') }}</span>
          <span class="mgmt-status-pill" :class="target.verified ? 'blue' : 'gray'">
            {{ target.verified ? $t('system_config.embedding_verified') : $t('system_config.embedding_pending_verify') }}
          </span>
        </div>
        <div class="sys-config-target-actions">
          <button
            class="btn-secondary btn-compact"
            :disabled="busy"
            @click="perform(() => api.post(`/admin/search/targets/${target.target_id}/verify`))"
          >
            {{ $t('system_config.embedding_verify') }}
          </button>
          <button
            class="btn-secondary btn-compact"
            :disabled="busy || !target.verified || target.status === 'active'"
            @click="perform(() => api.post(`/admin/search/targets/${target.target_id}/activate`))"
          >
            {{ $t('system_config.embedding_activate') }}
          </button>
        </div>
      </div>
    </div>

    <div class="sys-config-refresh">
      <button class="btn-ghost" :disabled="busy" @click="refreshStatus">
        <RefreshCw class="w-4 h-4" />
        {{ $t('system_config.embedding_refresh') }}
      </button>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.sys-config-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.9rem;
  font-size: 0.82rem;
  color: #475569;
}

label.sys-config-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.15rem;
  font-size: 0.8rem;
  font-weight: 500;
  color: #475569;
  cursor: pointer;
}

.sys-config-targets {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 1rem;
}

.sys-config-target-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.7);
  flex-wrap: wrap;
}

.sys-config-target-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: #475569;
}

.sys-config-target-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.btn-compact {
  padding: 0.35rem 0.7rem;
  font-size: 0.78rem;
}

.sys-config-refresh {
  margin-top: 0.9rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
