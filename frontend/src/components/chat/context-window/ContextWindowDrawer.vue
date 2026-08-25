<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import {
  AlertCircle,
  BarChart3,
  Database,
  FileText,
  Hash,
  Loader2,
  MessageSquareText,
  RefreshCw,
} from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import AppSideDrawer from '@/components/AppSideDrawer.vue'
import ContextCompactionView from '@/components/chat/context-window/ContextCompactionView.vue'
import type {
  ContextCompactionLocatePayload,
  ContextProviderTokens,
  ContextTokenCategorySummary,
  ContextTokenSegment,
  ContextWindowResponse,
} from '@/types/contextWindow'

const props = defineProps<{
  show: boolean
  level: number
  loading: boolean
  error: string | null
  data: ContextWindowResponse | null
  selectedCategory: string | null
  segmentsLoading: boolean
}>()

const emit = defineEmits<{
  close: []
  refresh: []
  selectCategory: [category: string]
  locate: [payload: ContextCompactionLocatePayload]
  'update:level': [value: number]
}>()

const { t } = useI18n()
const activeView = shallowRef<'attribution' | 'compaction'>('attribution')

const providerTokens = computed<ContextProviderTokens>(() => props.data?.provider_tokens || {
  available: false,
  status: 'unavailable',
})

const compaction = computed(() => props.data?.compaction || null)
const categories = computed(() => props.data?.categories || [])
const segments = computed(() => props.data?.segments || [])
const selectedSummary = computed(() => (
  categories.value.find((item) => item.category === props.selectedCategory) || null
))
const totalAttributionUnits = computed(() => (
  categories.value.reduce((sum, item) => sum + Number(item.attribution_units || 0), 0)
))

const tokenRows = computed(() => [
  ['input_tokens', t('chat.context_window_metric_input'), providerTokens.value.input_tokens],
  ['output_tokens', t('chat.context_window_metric_output'), providerTokens.value.output_tokens],
  ['cache_read_tokens', t('chat.context_window_metric_cache_read'), providerTokens.value.cache_read_tokens],
  ['cache_creation_tokens', t('chat.context_window_metric_cache_creation'), providerTokens.value.cache_creation_tokens],
  ['thinking_tokens', t('chat.context_window_metric_thinking'), providerTokens.value.thinking_tokens],
  ['tool_io_tokens', t('chat.context_window_metric_tool_io'), providerTokens.value.tool_io_tokens],
] as const)

const categoryLabel = (category: string): string => {
  const key = `chat.context_window_category_${category.toLowerCase()}`
  const label = t(key)
  return label === key ? category : label
}

const formatNumber = (value?: number | null): string => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return t('chat.context_window_unavailable')
  }
  return new Intl.NumberFormat().format(Number(value))
}

// Provider token 数据不可用时，即使字段是 0 也不应伪装成真实用量；归因单位数量仍用 formatNumber。
const formatMetric = (value?: number | null): string => {
  if (!providerTokens.value.available && (value === 0 || value === null || value === undefined)) {
    return t('chat.context_window_unavailable')
  }
  return formatNumber(value)
}

const formatPercent = (value?: number | null): string => {
  const numeric = Number(value || 0)
  return `${numeric.toFixed(numeric >= 10 ? 1 : 2)}%`
}

const formatCost = (value?: number | null): string => {
  if (value === null || value === undefined) return t('chat.context_window_unavailable')
  return `$${Number(value || 0).toFixed(4)}`
}

const formatDuration = (value?: number | null): string => {
  if (value === null || value === undefined) return t('chat.context_window_unavailable')
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(1)}s`
}

const AGENT_BACKEND_LABELS: Record<string, string> = {
  'claude-code': 'Claude Code CLI',
  opencode: 'OpenCode (Server)',
  dsh: 'DSH (JSON-RPC)',
  mock: 'Mock CLI',
}

const agentLabel = (value?: string | null): string => {
  if (!value) return t('chat.context_window_unavailable')
  return AGENT_BACKEND_LABELS[value] || value
}

const segmentRefLabel = (segment: ContextTokenSegment): string => {
  const refs = [
    segment.source_ref_id,
    segment.chat_message_id ? `msg:${segment.chat_message_id}` : '',
    segment.asset_id ? `asset:${segment.asset_id}` : '',
    segment.skill_runtime_event_id ? `skill-event:${segment.skill_runtime_event_id}` : '',
    segment.tool_use_id ? `tool:${segment.tool_use_id}` : '',
  ].filter(Boolean)
  return refs[0] || segment.source_kind
}

const categoryBarStyle = (item: ContextTokenCategorySummary) => ({
  width: `${Math.max(0, Math.min(100, Number(item.percentage || 0)))}%`,
})
</script>

<template>
  <AppSideDrawer
    :show="show"
    :title="$t('chat.context_window_title')"
    :level="level"
    resizable
    @close="emit('close')"
    @update:level="emit('update:level', $event)"
  >
    <template #icon>
      <BarChart3 class="w-4 h-4" />
    </template>
    <template #actions>
      <button type="button" class="icon-btn" :disabled="loading" :title="$t('common.refresh')" @click="emit('refresh')">
        <RefreshCw class="w-4 h-4" :class="{ spin: loading }" />
      </button>
    </template>

    <div class="context-window-shell">
      <div class="view-tabs-container">
        <div class="view-tabs" role="tablist" :aria-label="$t('chat.context_window_title')">
          <button
            type="button"
            class="view-tab"
            :class="{ active: activeView === 'attribution' }"
            data-test="attribution-tab"
            @click="activeView = 'attribution'"
          >
            <BarChart3 class="w-4 h-4" />
            <span>{{ $t('chat.context_window_tab_attribution') }}</span>
          </button>
          <button
            type="button"
            class="view-tab"
            :class="{ active: activeView === 'compaction' }"
            data-test="compaction-tab"
            @click="activeView = 'compaction'"
          >
            <Database class="w-4 h-4" />
            <span>{{ $t('chat.context_window_tab_compaction') }}</span>
          </button>
        </div>
      </div>

      <div v-if="loading && !data" class="drawer-state shell-state">
        <Loader2 class="w-5 h-5 spin" />
        <span>{{ $t('common.loading') }}</span>
      </div>

      <div v-else-if="error" class="drawer-state shell-state error">
        <AlertCircle class="w-5 h-5" />
        <span>{{ error }}</span>
      </div>

      <ContextCompactionView
        v-else-if="activeView === 'compaction'"
        :compaction="compaction"
        @locate="emit('locate', $event)"
      />

      <div v-else-if="!data?.snapshot" class="drawer-state shell-state">
        <Database class="w-5 h-5" />
        <span>{{ $t('chat.context_window_empty') }}</span>
      </div>

      <div v-else class="context-window-body">
        <section class="overview-panel">
          <div class="panel-heading">
            <span>{{ $t('chat.context_window_provider_overview') }}</span>
            <span class="status-pill" :class="{ unavailable: !providerTokens.available }">
              {{ providerTokens.available ? $t('chat.context_window_available') : $t('chat.context_window_unavailable') }}
            </span>
          </div>

          <div class="agent-line">
            <span>{{ $t('chat.context_window_metric_agent') }}</span>
            <strong>{{ agentLabel(data.snapshot.agent_backend) }}</strong>
          </div>

          <div class="total-token">
            <span>{{ $t('chat.context_window_metric_total') }}</span>
            <strong>{{ formatMetric(providerTokens.total_tokens) }}</strong>
          </div>

          <div class="distribution-bar" :aria-label="$t('chat.context_window_total_bar')">
            <span
              v-for="item in categories"
              :key="item.category"
              class="distribution-segment"
              :style="categoryBarStyle(item)"
              :title="`${categoryLabel(item.category)} ${formatPercent(item.percentage)}`"
            ></span>
          </div>

          <div class="metric-grid">
            <div v-for="row in tokenRows" :key="row[0]" class="metric-item">
              <span>{{ row[1] }}</span>
              <strong>{{ formatMetric(row[2]) }}</strong>
            </div>
            <div class="metric-item">
              <span>{{ $t('chat.context_window_metric_cost') }}</span>
              <strong>{{ formatCost(data.snapshot.total_cost_usd) }}</strong>
            </div>
            <div class="metric-item">
              <span>{{ $t('chat.context_window_metric_duration') }}</span>
              <strong>{{ formatDuration(data.snapshot.duration_ms) }}</strong>
            </div>
          </div>

          <p class="hint-line">{{ $t('chat.context_window_attribution_hint') }}</p>
        </section>

        <section class="category-panel">
          <div class="panel-heading">
            <span>{{ $t('chat.context_window_category_title') }}</span>
            <span>{{ formatNumber(totalAttributionUnits) }}</span>
          </div>

          <div v-if="categories.length === 0" class="inline-state">
            {{ $t('chat.context_window_category_empty') }}
          </div>

          <div v-else class="category-list">
            <button
              v-for="item in categories"
              :key="item.category"
              type="button"
              class="category-row"
              :class="{ active: item.category === selectedCategory }"
              @click="emit('selectCategory', item.category)"
            >
              <span class="category-name">{{ categoryLabel(item.category) }}</span>
              <span class="category-value">{{ formatNumber(item.attribution_units) }}</span>
              <span class="category-percent">{{ formatPercent(item.percentage) }}</span>
              <span class="category-track">
                <span class="category-fill" :style="categoryBarStyle(item)"></span>
              </span>
            </button>
          </div>
        </section>

        <section class="segments-panel">
          <div class="panel-heading">
            <span>{{ selectedSummary ? categoryLabel(selectedSummary.category) : $t('chat.context_window_segments_title') }}</span>
            <span v-if="selectedSummary">{{ selectedSummary.segment_count }}</span>
          </div>

          <div v-if="!selectedCategory" class="drawer-state muted">
            <MessageSquareText class="w-5 h-5" />
            <span>{{ $t('chat.context_window_select_category') }}</span>
          </div>

          <div v-else-if="segmentsLoading" class="drawer-state muted">
            <Loader2 class="w-5 h-5 spin" />
            <span>{{ $t('common.loading') }}</span>
          </div>

          <div v-else-if="segments.length === 0" class="drawer-state muted">
            <FileText class="w-5 h-5" />
            <span>{{ $t('chat.context_window_segments_empty') }}</span>
          </div>

          <div v-else class="segment-list">
            <article v-for="segment in segments" :key="segment.id" class="segment-row">
              <header class="segment-header">
                <div class="segment-title">{{ segment.title || segment.source_kind }}</div>
                <span>{{ formatNumber(segment.attribution_units) }}</span>
              </header>
              <p v-if="segment.preview" class="segment-preview">{{ segment.preview }}</p>
              <div class="segment-meta">
                <span>{{ segment.source_kind }}</span>
                <span>{{ segmentRefLabel(segment) }}</span>
                <span v-if="segment.content_hash"><Hash class="w-3 h-3" /> {{ segment.content_hash.slice(0, 10) }}</span>
              </div>
            </article>
          </div>
        </section>
      </div>
    </div>
  </AppSideDrawer>
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

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.icon-btn {
  width: 30px;
  height: 30px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  background: #ffffff;
  color: #475569;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.context-window-shell {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
}

.view-tabs-container {
  padding: 16px 20px 0;
  background: #f8fafc;
  display: flex;
}

.view-tabs {
  display: inline-flex;
  background: #e2e8f0;
  padding: 4px;
  border-radius: 12px;
  gap: 4px;
}

.view-tab {
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #64748b;
  min-height: 32px;
  padding: 6px 16px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.view-tab:hover {
  color: #0f172a;
}

.view-tab.active {
  background: #ffffff;
  color: #0ea5e9;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.context-window-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 300px 320px minmax(0, 1fr);
  gap: 16px;
  padding: 16px 20px;
  background: #f8fafc;
}

.overview-panel,
.category-panel,
.segments-panel {
  min-width: 0;
  min-height: 0;
  padding: 18px;
  overflow: auto;
  background: #ffffff;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 20px -2px rgba(0,0,0,0.03);
}

.panel-heading {
  min-height: 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.status-pill {
  border: 1px solid rgba(34, 197, 94, 0.35);
  border-radius: 999px;
  padding: 2px 8px;
  color: #166534;
  background: #f0fdf4;
  font-size: 11px;
}

.status-pill.unavailable {
  border-color: rgba(148, 163, 184, 0.45);
  color: #64748b;
  background: #f8fafc;
}

.agent-line {
  margin-top: 12px;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  color: #64748b;
  font-size: 12px;
}

.agent-line strong {
  color: #0f172a;
  font-size: 14px;
  overflow-wrap: anywhere;
}

.total-token {
  margin-top: 12px;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  color: #64748b;
  font-size: 12px;
}

.total-token strong {
  color: #0f172a;
  font-size: 22px;
  line-height: 1;
}

.distribution-bar {
  height: 10px;
  margin-top: 14px;
  border-radius: 999px;
  overflow: hidden;
  background: #e2e8f0;
  display: flex;
}

.distribution-segment {
  min-width: 2px;
  height: 100%;
  background: #0ea5e9;
}

.distribution-segment:nth-child(2n) { background: #22c55e; }
.distribution-segment:nth-child(3n) { background: #f59e0b; }
.distribution-segment:nth-child(4n) { background: #ef4444; }
.distribution-segment:nth-child(5n) { background: #6366f1; }

.metric-grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.metric-item {
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: #f8fafc;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.metric-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.03);
  border-color: #e2e8f0;
}

.metric-item span {
  color: #64748b;
  font-size: 12px;
}

.metric-item strong {
  color: #0f172a;
  font-size: 14px;
  overflow-wrap: anywhere;
}

.hint-line {
  margin-top: 12px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.category-list,
.segment-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.category-row {
  width: 100%;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 10px 12px;
  background: #ffffff;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 8px;
  align-items: center;
  text-align: left;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s ease;
}

.category-row:hover,
.category-row.active {
  border-color: #bae6fd;
  background: #f0f9ff;
  box-shadow: 0 2px 8px rgba(14, 165, 233, 0.05);
}

.category-name {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category-value,
.category-percent {
  font-size: 12px;
  color: #64748b;
}

.category-track {
  grid-column: 1 / -1;
  height: 5px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.category-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #0ea5e9;
}

.segment-row {
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 12px;
  background: #ffffff;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.segment-row:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.03);
  border-color: #e2e8f0;
}

.segment-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.segment-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.segment-preview {
  margin: 8px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.segment-meta {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: #64748b;
  font-size: 11px;
}

.segment-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.drawer-state,
.inline-state {
  min-height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #64748b;
  font-size: 13px;
  text-align: center;
  padding: 16px;
}

.drawer-state {
  grid-column: 1 / -1;
}

.drawer-state.shell-state {
  flex: 1;
  min-height: 0;
}

.drawer-state.error {
  color: #b91c1c;
}

.drawer-state.muted {
  min-height: 240px;
  grid-column: auto;
}

@media (max-width: 1320px) {
  .context-window-body {
    grid-template-columns: 280px 300px minmax(0, 1fr);
  }
}

@media (max-width: 980px) {
  .context-window-body {
    grid-template-columns: 1fr;
  }
}
</style>
