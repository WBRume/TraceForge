<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import {
  AlertTriangle,
  ArrowDown,
  Clock3,
  ExternalLink,
  GitBranch,
  Link2,
  SearchX,
} from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type {
  ContextCompactionEvent,
  ContextCompactionLocatePayload,
  ContextCompactionPhase,
  ContextCompactionResponse,
  ContextCompactionRisk,
} from '@/types/contextWindow'

const props = defineProps<{
  compaction: ContextCompactionResponse | null | undefined
}>()

const emit = defineEmits<{
  locate: [payload: ContextCompactionLocatePayload]
}>()

const { t } = useI18n()
const activeEventId = shallowRef('')

const phases = computed<ContextCompactionPhase[]>(() => props.compaction?.phases || [])
const events = computed<ContextCompactionEvent[]>(() => props.compaction?.events || [])
const hasEvents = computed(() => Boolean(props.compaction?.has_detected_events && events.value.length > 0))

const activeEvent = computed<ContextCompactionEvent | null>(() => (
  events.value.find((event) => event.id === activeEventId.value) || events.value[0] || null
))

watch(
  () => events.value.map((event) => event.id).join('|'),
  () => {
    activeEventId.value = events.value[0]?.id || ''
  },
  { immediate: true },
)

const selectPhase = (phase: ContextCompactionPhase) => {
  if (phase.compaction_event_id) {
    activeEventId.value = phase.compaction_event_id
  }
}

const formatNumber = (value?: number | null): string => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return t('chat.compaction_unavailable')
  }
  return new Intl.NumberFormat().format(Number(value))
}

const formatDate = (value?: string | null): string => {
  if (!value) return t('chat.compaction_unavailable')
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) return t('chat.compaction_unavailable')
  return new Intl.DateTimeFormat(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(parsed))
}

const phaseTokenLabel = (phase: ContextCompactionPhase): string => {
  if (phase.token_before_estimate !== null && phase.token_before_estimate !== undefined) {
    return formatNumber(phase.token_before_estimate)
  }
  return formatNumber(phase.token_after_estimate)
}

const locateEvent = (event: ContextCompactionEvent, preferred: 'message' | 'log' | 'job') => {
  const trigger = event.trigger || {}
  emit('locate', {
    source: event.source,
    source_ref_id: event.source_ref_id,
    ai_job_id: preferred === 'job' ? trigger.ai_job_id : trigger.ai_job_id,
    chat_message_id: preferred === 'message' ? trigger.chat_message_id : undefined,
    log_id: preferred === 'log' ? trigger.log_id : undefined,
  })
}

const riskToneClass = (risk: ContextCompactionRisk): string => {
  if (risk.level === 'high') return 'risk-high'
  if (risk.level === 'medium') return 'risk-medium'
  if (risk.level === 'low') return 'risk-low'
  return 'risk-unknown'
}
</script>

<template>
  <section class="compaction-view" data-test="compaction-view">
    <div v-if="!compaction" class="compaction-empty">
      <SearchX class="w-5 h-5" />
      <span>{{ $t('chat.compaction_no_data') }}</span>
    </div>

    <template v-else>
      <header class="compaction-summary">
        <div>
          <span class="summary-kicker">{{ $t('chat.compaction_title') }}</span>
          <strong>{{ hasEvents ? $t('chat.compaction_detected') : $t('chat.compaction_not_detected') }}</strong>
        </div>
        <span class="summary-pill" :class="{ detected: hasEvents }">
          {{ events.length }} {{ $t('chat.compaction_event_count') }}
        </span>
      </header>

      <div v-if="!hasEvents" class="no-compaction-state" data-test="compaction-empty">
        <SearchX class="w-5 h-5" />
        <div>
          <strong>{{ $t('chat.compaction_empty_title') }}</strong>
          <p>{{ $t('chat.compaction_empty_desc') }}</p>
        </div>
      </div>

      <div class="compaction-grid">
        <div class="compaction-left-col">
          <section class="phase-panel">
            <div class="section-heading">
              <GitBranch class="w-4 h-4" />
              <span>{{ $t('chat.compaction_phase_timeline') }}</span>
            </div>

            <div class="phase-timeline">
              <button
                v-for="phase in phases"
                :key="phase.phase_index"
                type="button"
                class="phase-row"
                :class="{ active: phase.compaction_event_id && phase.compaction_event_id === activeEvent?.id }"
                @click="selectPhase(phase)"
              >
                <span class="phase-marker">{{ phase.phase_index }}</span>
                <span class="phase-main">
                  <span class="phase-title">{{ $t('chat.compaction_phase') }} {{ phase.phase_index }}</span>
                  <span class="phase-time">{{ formatDate(phase.started_at) }} - {{ formatDate(phase.ended_at) }}</span>
                </span>
                <span class="phase-token">{{ phaseTokenLabel(phase) }}</span>
              </button>
            </div>
          </section>

          <section class="diagnostics-panel">
            <div class="section-heading">
              <span>{{ $t('chat.compaction_data_sources') }}</span>
            </div>

            <div class="data-sources">
              <div
                v-for="source in compaction.data_sources"
                :key="source.source"
                class="data-source-row"
              >
                <span>{{ source.source }}</span>
                <strong>{{ source.status }} · {{ source.event_count }}</strong>
              </div>
            </div>
          </section>
        </div>

        <div class="compaction-right-col">
          <section class="phase-detail-panel">
            <div class="section-heading">
              <Clock3 class="w-4 h-4" />
              <span>{{ $t('chat.compaction_phase_detail') }}</span>
            </div>

            <div v-if="activeEvent" class="event-detail" data-test="compaction-event-detail">
              <div class="event-head">
                <div>
                  <span class="summary-kicker">{{ $t('chat.compaction_event') }}</span>
                  <strong>{{ activeEvent.source_label || activeEvent.source }}</strong>
                </div>
                <time>{{ formatDate(activeEvent.detected_at) }}</time>
              </div>

              <div class="token-compare" data-test="compaction-token-compare">
                <div class="token-box">
                  <span>{{ $t('chat.compaction_token_before') }}</span>
                  <strong>{{ formatNumber(activeEvent.token_before_estimate) }}</strong>
                </div>
                <ArrowDown class="compare-arrow w-4 h-4" />
                <div class="token-box after">
                  <span>{{ $t('chat.compaction_token_after') }}</span>
                  <strong>{{ formatNumber(activeEvent.token_after_estimate) }}</strong>
                </div>
                <div class="token-box reduction">
                  <span>{{ $t('chat.compaction_token_reduction') }}</span>
                  <strong>{{ formatNumber(activeEvent.token_reduction_estimate) }}</strong>
                </div>
              </div>

              <p class="estimate-note">{{ $t('chat.compaction_estimated_hint') }}</p>
              <p v-if="activeEvent.preview" class="event-preview">{{ activeEvent.preview }}</p>

              <div class="locator-row">
                <button
                  v-if="activeEvent.trigger?.chat_message_id"
                  type="button"
                  class="locator-btn"
                  @click="locateEvent(activeEvent, 'message')"
                >
                  <Link2 class="w-3 h-3" />
                  {{ $t('chat.compaction_locate_message') }}
                </button>
                <button
                  v-if="activeEvent.trigger?.log_id"
                  type="button"
                  class="locator-btn"
                  @click="locateEvent(activeEvent, 'log')"
                >
                  <ExternalLink class="w-3 h-3" />
                  {{ $t('chat.compaction_locate_log') }}
                </button>
                <button
                  v-if="activeEvent.trigger?.ai_job_id"
                  type="button"
                  class="locator-btn"
                  @click="locateEvent(activeEvent, 'job')"
                >
                  <ExternalLink class="w-3 h-3" />
                  {{ $t('chat.compaction_locate_job') }}
                </button>
              </div>

              <div class="risk-list">
                <details
                  v-for="risk in activeEvent.risks"
                  :key="risk.kind"
                  class="risk-item"
                  :class="riskToneClass(risk)"
                  open
                >
                  <summary>
                    <AlertTriangle class="w-3 h-3" />
                    <span>{{ risk.label }}</span>
                    <strong>{{ formatNumber(risk.affected_segments) }}</strong>
                  </summary>
                  <p>{{ risk.reason }}</p>
                  <div v-if="risk.sample_refs.length" class="risk-refs">
                    <span v-for="ref in risk.sample_refs" :key="ref.id">
                      {{ ref.title || ref.source_kind }}
                    </span>
                  </div>
                </details>
              </div>
            </div>

            <div v-else class="phase-placeholder">
              <p class="estimate-note">{{ $t('chat.compaction_phase_only_hint') }}</p>
            </div>
          </section>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.w-3 {
  width: 12px;
  height: 12px;
}

.w-4 {
  width: 16px;
  height: 16px;
}

.w-5 {
  width: 20px;
  height: 20px;
}

.compaction-view {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px;
  overflow: auto;
  background: #f8fafc;
}

.compaction-summary,
.no-compaction-state,
.phase-panel,
.phase-detail-panel,
.diagnostics-panel {
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 4px 20px -2px rgba(0,0,0,0.03);
}

.compaction-summary {
  min-height: 56px;
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.summary-kicker {
  display: block;
  margin-bottom: 3px;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.compaction-summary strong,
.event-head strong {
  color: #0f172a;
  font-size: 14px;
}

.summary-pill {
  border: 1px solid rgba(148, 163, 184, 0.38);
  border-radius: 999px;
  padding: 4px 9px;
  color: #64748b;
  background: #f8fafc;
  font-size: 12px;
  white-space: nowrap;
}

.summary-pill.detected {
  border-color: rgba(14, 165, 233, 0.35);
  color: #0369a1;
  background: #f0f9ff;
}

.no-compaction-state,
.compaction-empty {
  min-height: 92px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #64748b;
  text-align: left;
  padding: 16px;
}

.no-compaction-state strong {
  display: block;
  color: #334155;
  font-size: 13px;
}

.no-compaction-state p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

.compaction-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: flex-start;
}

.compaction-left-col {
  flex: 1 1 280px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.compaction-right-col {
  flex: 2 1 320px;
  min-width: 0;
}

.phase-panel,
.phase-detail-panel,
.diagnostics-panel {
  padding: 18px;
}

.section-heading {
  min-height: 24px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.phase-timeline {
  position: relative;
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.phase-timeline::before {
  content: "";
  position: absolute;
  left: 13px;
  top: 12px;
  bottom: 12px;
  width: 1px;
  background: #cbd5e1;
}

.phase-row {
  position: relative;
  width: 100%;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 10px 12px;
  background: #ffffff;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.phase-row:hover,
.phase-row.active {
  border-color: #bae6fd;
  background: #f0f9ff;
  box-shadow: 0 2px 8px rgba(14, 165, 233, 0.05);
}

.phase-marker {
  position: relative;
  z-index: 1;
  width: 26px;
  height: 26px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #0369a1;
  background: #e0f2fe;
  font-size: 12px;
  font-weight: 800;
}

.phase-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.phase-title {
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.phase-time,
.phase-token {
  color: #64748b;
  font-size: 11px;
}

.phase-token {
  white-space: nowrap;
}

.event-detail {
  margin-top: 12px;
}

.event-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.event-head time {
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}

.token-compare {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.token-box {
  flex: 1 1 100px;
  min-width: 0;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: #f8fafc;
  transition: transform 0.2s ease;
}

.token-box:hover {
  transform: translateY(-2px);
  border-color: #e2e8f0;
}

.token-box span {
  color: #64748b;
  font-size: 11px;
}

.token-box strong {
  color: #0f172a;
  font-size: 16px;
  overflow-wrap: anywhere;
}

.token-box.after strong {
  color: #047857;
}

.token-box.reduction strong {
  color: #b45309;
}

.compare-arrow {
  flex-shrink: 0;
  color: #94a3b8;
  margin: 0 4px;
}

.estimate-note {
  margin: 10px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.event-preview {
  margin: 10px 0 0;
  border-radius: 8px;
  background: #f8fafc;
  padding: 9px;
  color: #334155;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.locator-row {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.locator-btn {
  border: 1px solid rgba(14, 165, 233, 0.35);
  border-radius: 8px;
  background: #f0f9ff;
  color: #0369a1;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  font-size: 12px;
  cursor: pointer;
}

.risk-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.risk-item {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 10px 12px;
  transition: all 0.2s ease;
}

.risk-item summary {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto;
  gap: 6px;
  align-items: center;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.risk-item summary::-webkit-details-marker {
  display: none;
}

.risk-item p {
  margin: 7px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
}

.risk-medium {
  background: #fefce8;
  border-color: #fde68a;
}

.risk-high {
  background: #fef2f2;
  border-color: #fecaca;
}

.risk-low {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.risk-unknown {
  background: #f8fafc;
}

.risk-refs {
  margin-top: 7px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.risk-refs span {
  max-width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 999px;
  padding: 2px 7px;
  color: #475569;
  background: #ffffff;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.data-sources {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.data-source-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #64748b;
  font-size: 11px;
}

.data-source-row strong {
  color: #334155;
  font-weight: 700;
}


</style>
