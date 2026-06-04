<script setup lang="ts">
import { onBeforeUnmount, reactive, watch } from 'vue'
import { Save } from 'lucide-vue-next'
import type { ApiMockEndpoint, ApiMockRule } from '@/types/apiMock'

const props = defineProps<{
  endpoint: ApiMockEndpoint | null
  rule: ApiMockRule | null
  canManage: boolean
  savingEndpoint: boolean
  savingRule: boolean
}>()

const emit = defineEmits<{
  (e: 'save-endpoint', payload: {
    row_version: number
    operation_id: string | null
    tag: string | null
    summary: string | null
    request_schema_json: Record<string, unknown> | null
    response_schema_json: Record<string, unknown> | null
    entity_refs_json: string[] | null
  }): void
  (e: 'save-rule', payload: {
    row_version?: number
    mode: 'STATIC' | 'MOCKJS' | 'PROXY'
    static_body_json?: Record<string, unknown> | null
    mockjs_template?: string | null
    status_code: number
    headers_json?: Record<string, unknown> | null
    cookies_json?: Array<Record<string, unknown>> | null
    delay_ms: number
    enabled: boolean
  }): void
  (e: 'draft-change', payload: {
    endpoint_id: string
    endpoint: {
      operation_id: string | null
      tag: string | null
      summary: string | null
    }
    rule: {
      mode: 'STATIC' | 'MOCKJS' | 'PROXY'
      status_code: number
      delay_ms: number
      enabled: boolean
    }
  }): void
}>()

const endpointForm = reactive({
  operation_id: '',
  tag: '',
  summary: '',
  request_schema_text: '{}',
  response_schema_text: '{}',
  entity_refs_text: '',
  row_version: 1,
})

const ruleForm = reactive({
  row_version: 1,
  mode: 'STATIC' as 'STATIC' | 'MOCKJS' | 'PROXY',
  static_body_text: '{}',
  mockjs_template: '',
  status_code: 200,
  headers_text: '{}',
  cookies_text: '[]',
  delay_ms: 0,
  enabled: true,
})

let suppressDraftEmit = false
let draftEmitTimer: number | null = null

const parseJson = <T>(raw: string, fallback: T): T => {
  const text = (raw || '').trim()
  if (!text) return fallback
  try {
    return JSON.parse(text) as T
  } catch {
    return fallback
  }
}

watch(
  () => props.endpoint,
  (endpoint) => {
    suppressDraftEmit = true
    if (!endpoint) {
      endpointForm.operation_id = ''
      endpointForm.tag = ''
      endpointForm.summary = ''
      endpointForm.request_schema_text = '{}'
      endpointForm.response_schema_text = '{}'
      endpointForm.entity_refs_text = ''
      endpointForm.row_version = 1
      queueMicrotask(() => {
        suppressDraftEmit = false
      })
      return
    }
    endpointForm.operation_id = endpoint.operation_id || ''
    endpointForm.tag = endpoint.tag || ''
    endpointForm.summary = endpoint.summary || ''
    endpointForm.request_schema_text = JSON.stringify(endpoint.request_schema_json || {}, null, 2)
    endpointForm.response_schema_text = JSON.stringify(endpoint.response_schema_json || {}, null, 2)
    endpointForm.entity_refs_text = (endpoint.entity_refs_json || []).join(', ')
    endpointForm.row_version = endpoint.row_version
    queueMicrotask(() => {
      suppressDraftEmit = false
    })
  },
  { immediate: true },
)

watch(
  () => props.rule,
  (rule) => {
    suppressDraftEmit = true
    if (!rule) {
      ruleForm.row_version = 1
      ruleForm.mode = 'STATIC'
      ruleForm.static_body_text = '{}'
      ruleForm.mockjs_template = ''
      ruleForm.status_code = 200
      ruleForm.headers_text = '{}'
      ruleForm.cookies_text = '[]'
      ruleForm.delay_ms = 0
      ruleForm.enabled = true
      queueMicrotask(() => {
        suppressDraftEmit = false
      })
      return
    }
    ruleForm.row_version = rule.row_version
    ruleForm.mode = rule.mode
    ruleForm.static_body_text = JSON.stringify(rule.static_body_json || {}, null, 2)
    ruleForm.mockjs_template = rule.mockjs_template || ''
    ruleForm.status_code = rule.status_code
    ruleForm.headers_text = JSON.stringify(rule.headers_json || {}, null, 2)
    ruleForm.cookies_text = JSON.stringify(rule.cookies_json || [], null, 2)
    ruleForm.delay_ms = rule.delay_ms
    ruleForm.enabled = rule.enabled
    queueMicrotask(() => {
      suppressDraftEmit = false
    })
  },
  { immediate: true },
)

const scheduleDraftEmit = () => {
  if (suppressDraftEmit || !props.endpoint) return

  if (draftEmitTimer !== null) {
    window.clearTimeout(draftEmitTimer)
  }

  draftEmitTimer = window.setTimeout(() => {
    draftEmitTimer = null
    if (!props.endpoint || suppressDraftEmit) return

    emit('draft-change', {
      endpoint_id: props.endpoint.id,
      endpoint: {
        operation_id: endpointForm.operation_id || null,
        tag: endpointForm.tag || null,
        summary: endpointForm.summary || null,
      },
      rule: {
        mode: ruleForm.mode,
        status_code: Number(ruleForm.status_code),
        delay_ms: Number(ruleForm.delay_ms),
        enabled: Boolean(ruleForm.enabled),
      },
    })
  }, 320)
}

watch(
  () => [
    endpointForm.operation_id,
    endpointForm.tag,
    endpointForm.summary,
    ruleForm.mode,
    ruleForm.status_code,
    ruleForm.delay_ms,
    ruleForm.enabled,
  ],
  () => {
    scheduleDraftEmit()
  },
)

onBeforeUnmount(() => {
  if (draftEmitTimer !== null) {
    window.clearTimeout(draftEmitTimer)
    draftEmitTimer = null
  }
})

const submitEndpoint = () => {
  if (!props.canManage || !props.endpoint) return
  const refs = endpointForm.entity_refs_text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  emit('save-endpoint', {
    row_version: endpointForm.row_version,
    operation_id: endpointForm.operation_id || null,
    tag: endpointForm.tag || null,
    summary: endpointForm.summary || null,
    request_schema_json: parseJson(endpointForm.request_schema_text, {}),
    response_schema_json: parseJson(endpointForm.response_schema_text, {}),
    entity_refs_json: refs.length > 0 ? refs : null,
  })
}

const submitRule = () => {
  if (!props.canManage || !props.endpoint) return
  emit('save-rule', {
    row_version: props.rule ? ruleForm.row_version : undefined,
    mode: ruleForm.mode,
    static_body_json: parseJson<Record<string, unknown>>(ruleForm.static_body_text, {}),
    mockjs_template: ruleForm.mockjs_template || null,
    status_code: Number(ruleForm.status_code),
    headers_json: parseJson<Record<string, unknown>>(ruleForm.headers_text, {}),
    cookies_json: parseJson<Array<Record<string, unknown>>>(ruleForm.cookies_text, []),
    delay_ms: Number(ruleForm.delay_ms),
    enabled: Boolean(ruleForm.enabled),
  })
}
</script>

<template>
  <section class="panel glass-panel">
    <header class="head">
      <h3>{{ $t('api_mock.endpoint_editor') }}</h3>
      <span v-if="endpoint" class="endpoint-id">{{ endpoint.method }} {{ endpoint.path }}</span>
    </header>

    <div v-if="!endpoint" class="empty">{{ $t('api_mock.select_endpoint_hint') }}</div>

    <template v-else>
      <div class="sub-block">
        <h4>{{ $t('api_mock.endpoint_meta') }}</h4>
        <div class="grid">
          <label class="field">
            <span>operationId</span>
            <input v-model="endpointForm.operation_id" class="input-field" :disabled="!canManage" />
          </label>
          <label class="field">
            <span>tag</span>
            <input v-model="endpointForm.tag" class="input-field" :disabled="!canManage" />
          </label>
        </div>
        <label class="field">
          <span>{{ $t('api_mock.summary') }}</span>
          <input v-model="endpointForm.summary" class="input-field" :disabled="!canManage" />
        </label>
        <div class="grid">
          <label class="field">
            <span>{{ $t('api_mock.request_schema') }}</span>
            <textarea v-model="endpointForm.request_schema_text" class="input-field textarea" :disabled="!canManage" />
          </label>
          <label class="field">
            <span>{{ $t('api_mock.response_schema') }}</span>
            <textarea v-model="endpointForm.response_schema_text" class="input-field textarea" :disabled="!canManage" />
          </label>
        </div>
        <label class="field">
          <span>{{ $t('api_mock.entity_refs') }}</span>
          <input v-model="endpointForm.entity_refs_text" class="input-field" :placeholder="$t('api_mock.entity_refs_placeholder')" :disabled="!canManage" />
        </label>
        <button type="button" class="btn-secondary mini" :disabled="!canManage || savingEndpoint" @click="submitEndpoint">
          <Save class="w-4 h-4" />
          {{ savingEndpoint ? $t('api_mock.saving') : $t('api_mock.save_endpoint') }}
        </button>
      </div>

      <div class="sub-block">
        <h4>{{ $t('api_mock.rule_editor') }}</h4>
        <div class="grid">
          <label class="field">
            <span>{{ $t('api_mock.rule_mode') }}</span>
            <select v-model="ruleForm.mode" class="input-field" :disabled="!canManage">
              <option value="STATIC">STATIC</option>
              <option value="MOCKJS">MOCKJS</option>
              <option value="PROXY">PROXY</option>
            </select>
          </label>
          <label class="field">
            <span>{{ $t('api_mock.status_code') }}</span>
            <input v-model.number="ruleForm.status_code" type="number" min="100" max="599" class="input-field" :disabled="!canManage" />
          </label>
        </div>
        <div class="grid">
          <label class="field">
            <span>{{ $t('api_mock.delay_ms') }}</span>
            <input v-model.number="ruleForm.delay_ms" type="number" min="0" class="input-field" :disabled="!canManage" />
          </label>
          <label class="field checkbox">
            <span>{{ $t('api_mock.enabled') }}</span>
            <input v-model="ruleForm.enabled" type="checkbox" :disabled="!canManage" />
          </label>
        </div>
        <label class="field">
          <span>{{ $t('api_mock.static_body') }}</span>
          <textarea v-model="ruleForm.static_body_text" class="input-field textarea" :disabled="!canManage" />
        </label>
        <label class="field">
          <span>{{ $t('api_mock.mockjs_template') }}</span>
          <textarea v-model="ruleForm.mockjs_template" class="input-field textarea" :disabled="!canManage" />
        </label>
        <div class="grid">
          <label class="field">
            <span>{{ $t('api_mock.headers_json') }}</span>
            <textarea v-model="ruleForm.headers_text" class="input-field textarea sm" :disabled="!canManage" />
          </label>
          <label class="field">
            <span>{{ $t('api_mock.cookies_json') }}</span>
            <textarea v-model="ruleForm.cookies_text" class="input-field textarea sm" :disabled="!canManage" />
          </label>
        </div>
        <button type="button" class="btn-primary mini" :disabled="!canManage || savingRule" @click="submitRule">
          <Save class="w-4 h-4" />
          {{ savingRule ? $t('api_mock.saving') : $t('api_mock.save_rule') }}
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.panel {
  padding: 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.head h3 {
  margin: 0;
  font-size: 0.92rem;
  color: #0f172a;
}

.endpoint-id {
  font-size: 0.72rem;
  color: #0369a1;
}

.empty {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  background: #f8fbff;
}

.sub-block {
  border: 1px solid #dbeafe;
  border-radius: 12px;
  padding: 0.7rem;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.sub-block h4 {
  margin: 0;
  font-size: 0.82rem;
  color: #0c4a6e;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}

.field span {
  font-size: 0.73rem;
  color: #475569;
}

.textarea {
  min-height: 90px;
  resize: vertical;
  padding-top: 0.6rem;
}

.textarea.sm {
  min-height: 72px;
}

.checkbox {
  justify-content: flex-end;
}

.checkbox input {
  width: 16px;
  height: 16px;
  margin-top: 0.15rem;
}

.mini {
  align-self: flex-end;
  padding: 0.42rem 0.78rem;
  font-size: 0.78rem;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
