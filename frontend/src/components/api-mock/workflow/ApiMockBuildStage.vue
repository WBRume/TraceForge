<script setup lang="ts">
import type { ApiMockEndpoint, ApiMockPreviewResponse, ApiMockRule } from '@/types/apiMock'
import EndpointEditorPanel from '@/components/api-mock/EndpointEditorPanel.vue'
import PreviewPanel from '@/components/api-mock/PreviewPanel.vue'

defineProps<{
  endpoint: ApiMockEndpoint | null
  rule: ApiMockRule | null
  canManage: boolean
  savingEndpoint: boolean
  savingRule: boolean
  preview: ApiMockPreviewResponse | null
  previewBusy: boolean
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
  (e: 'run-preview', payload: { method: string; path: string; body: unknown }): void
  (e: 'back'): void
}>()
</script>

<template>
  <section class="stage-view">
    <header class="stage-head">
      <div class="stage-copy">
        <span class="stage-kicker">04 / {{ $t('api_mock.stage_build') }}</span>
        <h2 class="stage-title">{{ $t('api_mock.stage_build') }}</h2>
        <p class="stage-subtitle">{{ endpoint?.summary || $t('api_mock.build_intro') }}</p>
      </div>
      <div v-if="endpoint" class="endpoint-chip-row">
        <span class="method-chip" :class="`method-${endpoint.method.toLowerCase()}`">{{ endpoint.method }}</span>
        <span class="path-chip">{{ endpoint.path }}</span>
      </div>
    </header>

    <div class="build-grid">
      <EndpointEditorPanel
        :endpoint="endpoint"
        :rule="rule"
        :can-manage="canManage"
        :saving-endpoint="savingEndpoint"
        :saving-rule="savingRule"
        @save-endpoint="emit('save-endpoint', $event)"
        @save-rule="emit('save-rule', $event)"
        @draft-change="emit('draft-change', $event)"
      />
      <PreviewPanel
        :endpoint="endpoint"
        :preview="preview"
        :preview-busy="previewBusy"
        @run-preview="emit('run-preview', $event)"
      />
    </div>

    <footer class="stage-footer">
      <button type="button" class="btn-secondary stage-btn ghost" @click="emit('back')">
        {{ $t('api_mock.step_back') }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.stage-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 100%;
}

.stage-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.stage-copy {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.stage-kicker {
  color: #0369a1;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.stage-title {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: clamp(1.45rem, 2vw, 1.95rem);
  color: #1e3a8a;
}

.stage-subtitle {
  margin: 0;
  color: #64748b;
  font-size: 0.92rem;
  line-height: 1.72;
}

.endpoint-chip-row {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.55rem;
}

.method-chip,
.path-chip {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: 0.28rem 0.78rem;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
}

.method-chip {
  color: #ffffff;
}

.method-chip.method-get { background: linear-gradient(135deg, #10b981, #059669); }
.method-chip.method-post { background: linear-gradient(135deg, #0ea5e9, #2563eb); }
.method-chip.method-put,
.method-chip.method-patch { background: linear-gradient(135deg, #f59e0b, #ea580c); }
.method-chip.method-delete { background: linear-gradient(135deg, #ef4444, #dc2626); }

.path-chip {
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.84);
  color: #0369a1;
  max-width: 28rem;
}

.build-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.32fr) minmax(320px, 0.88fr);
  gap: 1rem;
  min-height: 0;
}

.stage-footer {
  display: flex;
  align-items: center;
  justify-content: flex-start;
}

.stage-btn {
  min-width: 8rem;
  min-height: 2.8rem;
  border-radius: 14px;
}

.btn-secondary.ghost {
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.76);
  color: #0369a1;
  font-weight: 700;
}

@media (max-width: 1120px) {
  .build-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .stage-head {
    flex-direction: column;
  }

  .endpoint-chip-row {
    justify-content: flex-start;
  }
}
</style>
