<script setup lang="ts">
import { onMounted, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { BrainCircuit, RefreshCw } from '@/components/icons'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

interface EmbeddingProfile {
  id: string
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
const props = defineProps<{ revision: number }>()
const emit = defineEmits<{ changed: [] }>()
const profile = shallowRef<EmbeddingProfile | null>(null)
const busy = shallowRef(false)
const targets = shallowRef<SearchTarget[]>([])

const load = async () => {
  const { data } = await api.get('/admin/search/embedding')
  targets.value = (data.targets || []) as SearchTarget[]
  profile.value = (data.profiles?.[0] || null) as EmbeddingProfile | null
}

const perform = async (action: () => Promise<unknown>) => {
  busy.value = true
  try {
    await action()
    await load()
    emit('changed')
    ElMessage.success(t('system_config.embedding_operation_success'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('system_config.embedding_operation_failed'), t))
  } finally {
    busy.value = false
  }
}

const refreshStatus = () => perform(async () => {})

onMounted(() => {
  void load().catch(() => ElMessage.error(t('system_config.embedding_load_failed')))
})
watch(() => props.revision, () => {
  void load().catch(() => ElMessage.error(t('system_config.embedding_load_failed')))
})
</script>

<template>
  <section class="index-management" :aria-label="t('feature_config.index_management')">
    <div class="sys-config-row">
      <div class="sys-config-info">
        <h3 class="sys-config-name">
          <BrainCircuit class="w-4 h-4" />
          {{ t('feature_config.index_management') }}
        </h3>
        <p class="mgmt-hint">{{ t('feature_config.index_hint') }}</p>
      </div>
    </div>

    <div class="sys-config-actions">
      <button
        type="button"
        class="btn-secondary"
        :disabled="busy || !profile"
        @click="perform(() => api.post(`/admin/search/embedding/${profile?.id}/test`))"
      >
        {{ $t('system_config.embedding_test') }}
      </button>
      <button
        type="button"
        class="btn-secondary"
        :disabled="busy || !profile?.dimension"
        @click="perform(() => api.post(`/admin/search/embedding/${profile?.id}/build`))"
      >
        {{ $t('system_config.embedding_build') }}
      </button>
    </div>

    <div v-if="profile" class="sys-config-status">
      <span class="mgmt-status-pill blue">{{ profile.status }}</span>
      <span>{{ profile.model_id }}</span>
      <span>
        {{ $t('system_config.embedding_dimension') }}：{{ profile.dimension || $t('system_config.embedding_dimension_unknown') }}
      </span>
    </div>
    <p v-else class="index-empty">{{ t('feature_config.index_empty') }}</p>

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
            type="button"
            class="btn-secondary btn-compact"
            :disabled="busy"
            @click="perform(() => api.post(`/admin/search/targets/${target.target_id}/verify`))"
          >
            {{ $t('system_config.embedding_verify') }}
          </button>
          <button
            type="button"
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
      <button type="button" class="btn-ghost" :disabled="busy" @click="refreshStatus">
        <RefreshCw class="w-4 h-4" />
        {{ $t('system_config.embedding_refresh') }}
      </button>
    </div>
  </section>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.index-management { margin-top: 32px; padding-top: 24px; border-top: 1px solid #e2e8f0; }
.index-empty { color: #64748b; font-size: 12px; }
.sys-config-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.9rem;
  font-size: 0.82rem;
  color: #475569;
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
