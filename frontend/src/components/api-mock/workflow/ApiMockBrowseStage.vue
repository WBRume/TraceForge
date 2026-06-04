<script setup lang="ts">
import type { ApiMockEndpoint, ApiMockEntity } from '@/types/apiMock'
import EndpointTreePanel from '@/components/api-mock/EndpointTreePanel.vue'
import EntityPanel from '@/components/api-mock/EntityPanel.vue'

defineProps<{
  endpoints: ApiMockEndpoint[]
  selectedEndpointId: string
  keyword: string
  entities: ApiMockEntity[]
  currentSourceLabel: string
  selectedEndpoint: ApiMockEndpoint | null
  canManage: boolean
}>()

const emit = defineEmits<{
  (e: 'update:keyword', value: string): void
  (e: 'select-endpoint', endpointId: string): void
  (e: 'back'): void
  (e: 'next'): void
}>()
</script>

<template>
  <section class="stage-view">
    <header class="stage-head">
      <div class="stage-copy">
        <span class="stage-kicker">03 / {{ $t('api_mock.stage_browse') }}</span>
        <h2 class="stage-title">{{ $t('api_mock.stage_browse') }}</h2>
        <p class="stage-subtitle">{{ $t('api_mock.endpoint_intro') }}</p>
      </div>
      <div class="stage-summary-card">
        <span class="summary-label">{{ $t('api_mock.current_source_label') }}</span>
        <strong>{{ currentSourceLabel }}</strong>
        <p>{{ endpoints.length }} {{ $t('api_mock.hero_metric_endpoints') }} / {{ entities.length }} {{ $t('api_mock.entity_title') }}</p>
      </div>
    </header>

    <div class="browse-grid">
      <EndpointTreePanel
        :endpoints="endpoints"
        :selected-endpoint-id="selectedEndpointId"
        :keyword="keyword"
        @update:keyword="emit('update:keyword', $event)"
        @select="emit('select-endpoint', $event)"
      />
      <EntityPanel 
        :entities="entities"
        :endpoint="selectedEndpoint"
        :can-manage="canManage" 
      />
    </div>

    <footer class="stage-footer">
      <button type="button" class="btn-secondary stage-btn ghost" @click="emit('back')">
        {{ $t('api_mock.step_back') }}
      </button>
      <button type="button" class="btn-primary stage-btn" :disabled="!selectedEndpoint" @click="emit('next')">
        {{ $t('api_mock.step_continue') }}
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

.stage-kicker,
.summary-label {
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

.stage-summary-card {
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.95rem 1rem;
  border-radius: 22px;
  border: 1px solid rgba(191, 219, 254, 0.95);
  background: #ffffff;
}

.stage-summary-card strong {
  color: #0f172a;
  font-size: 0.95rem;
  line-height: 1.5;
}

.stage-summary-card p {
  margin: 0;
  color: #64748b;
  font-size: 0.82rem;
  line-height: 1.6;
}

.browse-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  gap: 1rem;
  min-height: 0;
}

.stage-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
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
  .browse-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .stage-head {
    flex-direction: column;
  }

  .stage-summary-card {
    min-width: 0;
    width: 100%;
  }
}
</style>
