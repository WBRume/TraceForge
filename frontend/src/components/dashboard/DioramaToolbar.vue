<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Box,
  Layers,
  Maximize2,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
  RotateCw,
  Search,
  Tag,
  Users,
} from '@/components/icons'
import type {
  DioramaIsoMode,
  DioramaMetric,
  DioramaRepoItem,
  DioramaSearchEntry,
} from '@/types/dashboardDiorama'

const props = defineProps<{
  repos: DioramaRepoItem[]
  enabledRepoIds: Set<string>
  metric: DioramaMetric
  days: 14 | 30 | 60
  isoMode: DioramaIsoMode
  zoomPct: number
  showAvatars: boolean
  showLabels: boolean
  loading: boolean
  searchCorpus: DioramaSearchEntry[]
}>()

const emit = defineEmits<{
  'toggle-repo': [repoId: string]
  'focus-repo': [repoId: string]
  'update:metric': [value: DioramaMetric]
  'update:days': [value: 14 | 30 | 60]
  'update:iso-mode': [value: DioramaIsoMode]
  'update:show-avatars': [value: boolean]
  'update:show-labels': [value: boolean]
  rotate: [dir: 1 | -1]
  zoom: [factor: number]
  'reset-view': []
  refresh: []
  'search-change': [moduleIds: Set<string>]
  'select-search-module': [moduleId: string]
}>()

const { t } = useI18n()

const searchQuery = shallowRef('')
const searchFocused = shallowRef(false)

const metricOptions = computed<Array<{ value: DioramaMetric; label: string }>>(() => [
  { value: 'heat', label: t('dashboard.diorama.metric_heat') },
  { value: 'loc', label: t('dashboard.diorama.metric_loc') },
  { value: 'impact', label: t('dashboard.diorama.metric_impact') },
])

const dayOptions = [14, 30, 60] as const

const searchHits = computed(() => {
  const q = searchQuery.value.trim().toLocaleLowerCase()
  if (!q) return []
  return props.searchCorpus
    .filter(item => item.name.toLocaleLowerCase().includes(q) || item.path.toLocaleLowerCase().includes(q))
    .slice(0, 10)
})

const showDropdown = computed(() => searchFocused.value && searchQuery.value.trim().length > 0)

watch(searchQuery, (raw) => {
  const q = raw.trim().toLocaleLowerCase()
  if (!q) {
    emit('search-change', new Set())
    return
  }
  const matched = new Set<string>()
  for (const item of props.searchCorpus) {
    if (item.name.toLocaleLowerCase().includes(q) || item.path.toLocaleLowerCase().includes(q)) {
      matched.add(item.moduleId)
    }
  }
  emit('search-change', matched)
})

function handleSelectHit(entry: DioramaSearchEntry) {
  emit('select-search-module', entry.moduleId)
  searchFocused.value = false
}

function handleSearchEnter() {
  const first = searchHits.value[0]
  if (first) handleSelectHit(first)
}

function handleSearchBlur() {
  window.setTimeout(() => {
    searchFocused.value = false
  }, 160)
}

function formatLoc(loc: number): string {
  return loc >= 1000 ? `${(loc / 1000).toFixed(1)}k` : String(loc)
}
</script>

<template>
  <div class="diorama-toolbar">
    <div class="toolbar-row toolbar-row-top">
      <div class="repo-pills" :title="t('dashboard.diorama.repo_filter_hint')">
        <button
          v-for="repo in repos"
          :key="repo.id"
          type="button"
          class="repo-pill"
          :class="{
            'is-active': enabledRepoIds.has(repo.id),
            'is-pending': !repo.available,
          }"
          :title="t('dashboard.diorama.repo_pill_tooltip', { name: repo.name, branch: repo.branch })"
          @click="emit('toggle-repo', repo.id)"
          @dblclick.stop="emit('focus-repo', repo.id)"
        >
          <span class="repo-dot" :style="{ backgroundColor: repo.color }" />
          <span class="repo-name">{{ repo.name }}</span>
          <span class="repo-loc">{{ formatLoc(repo.loc) }}</span>
          <span v-if="!repo.available" class="repo-state-tag">{{ t('dashboard.diorama.repo_pending') }}</span>
        </button>
      </div>

      <div class="toolbar-right-actions">
        <div class="search-box">
          <el-input
            v-model="searchQuery"
            size="small"
            clearable
            :placeholder="t('dashboard.diorama.search_placeholder')"
            @focus="searchFocused = true"
            @blur="handleSearchBlur"
            @keydown.enter.prevent="handleSearchEnter"
          >
            <template #prefix>
              <Search class="input-icon" />
            </template>
          </el-input>

          <div v-if="showDropdown" class="search-dropdown">
            <template v-if="searchHits.length">
              <button
                v-for="hit in searchHits"
                :key="`${hit.kind}:${hit.path}`"
                type="button"
                class="search-hit-item"
                @mousedown.prevent="handleSelectHit(hit)"
              >
                <span class="hit-kind" :class="hit.kind === 'module' ? 'is-module' : 'is-file'">
                  {{ hit.kind === 'module' ? t('dashboard.diorama.kind_module') : t('dashboard.diorama.kind_file') }}
                </span>
                <span class="hit-main">
                  <span class="hit-name">{{ hit.name }}</span>
                  <span class="hit-path">{{ hit.path }}</span>
                </span>
                <span class="hit-meta">{{ formatLoc(hit.loc) }}</span>
              </button>
            </template>
            <div v-else class="search-empty">{{ t('dashboard.diorama.search_empty') }}</div>
          </div>
        </div>

        <div class="segmented-group" role="group" :aria-label="t('dashboard.diorama.days_label')">
          <button
            v-for="d in dayOptions"
            :key="d"
            type="button"
            class="seg-btn"
            :class="{ 'is-active': days === d }"
            @click="emit('update:days', d)"
          >
            {{ t('dashboard.diorama.days_unit', { count: d }) }}
          </button>
        </div>

        <el-button
          size="small"
          class="refresh-btn"
          :disabled="loading"
          :title="t('dashboard.diorama.refresh')"
          @click="emit('refresh')"
        >
          <RefreshCw class="btn-icon" :class="{ 'is-spinning': loading }" />
        </el-button>
      </div>
    </div>

    <div class="toolbar-row toolbar-row-bottom">
      <div class="toolbar-group">
        <span class="group-label">{{ t('dashboard.diorama.height_metric') }}</span>
        <div class="segmented-group" role="group">
          <button
            v-for="opt in metricOptions"
            :key="opt.value"
            type="button"
            class="seg-btn"
            :class="{ 'is-active': metric === opt.value }"
            @click="emit('update:metric', opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>

        <span class="toolbar-divider" aria-hidden="true" />

        <button
          type="button"
          class="toggle-chip"
          :class="{ 'is-active': showAvatars }"
          @click="emit('update:show-avatars', !showAvatars)"
        >
          <Users class="chip-icon" />
          <span>{{ t('dashboard.diorama.layer_avatars') }}</span>
        </button>
        <button
          type="button"
          class="toggle-chip"
          :class="{ 'is-active': showLabels }"
          @click="emit('update:show-labels', !showLabels)"
        >
          <Tag class="chip-icon" />
          <span>{{ t('dashboard.diorama.layer_labels') }}</span>
        </button>
      </div>

      <div class="toolbar-group camera-controls">
        <div class="icon-btn-group">
          <button
            type="button"
            class="icon-btn"
            :title="t('dashboard.diorama.rotate_ccw')"
            @click="emit('rotate', -1)"
          >
            <RotateCcw class="btn-icon" />
          </button>
          <button
            type="button"
            class="icon-btn"
            :title="t('dashboard.diorama.rotate_cw')"
            @click="emit('rotate', 1)"
          >
            <RotateCw class="btn-icon" />
          </button>
        </div>

        <div class="segmented-group" role="group">
          <button
            type="button"
            class="seg-btn"
            :class="{ 'is-active': isoMode === '3d' }"
            @click="emit('update:iso-mode', '3d')"
          >
            <Box class="chip-icon" />
            <span>{{ t('dashboard.diorama.view_3d') }}</span>
          </button>
          <button
            type="button"
            class="seg-btn"
            :class="{ 'is-active': isoMode === 'top' }"
            @click="emit('update:iso-mode', 'top')"
          >
            <Layers class="chip-icon" />
            <span>{{ t('dashboard.diorama.view_top') }}</span>
          </button>
        </div>

        <div class="zoom-group">
          <button type="button" class="icon-btn" :title="t('dashboard.diorama.zoom_out')" @click="emit('zoom', 1 / 1.2)">
            <Minus class="btn-icon" />
          </button>
          <button type="button" class="zoom-pct-btn" :title="t('dashboard.diorama.reset_view')" @click="emit('reset-view')">
            {{ zoomPct }}%
          </button>
          <button type="button" class="icon-btn" :title="t('dashboard.diorama.zoom_in')" @click="emit('zoom', 1.2)">
            <Plus class="btn-icon" />
          </button>
          <button type="button" class="icon-btn" :title="t('dashboard.diorama.reset_view')" @click="emit('reset-view')">
            <Maximize2 class="btn-icon" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diorama-toolbar {
  display: flex;
  flex-direction: column;
  background: var(--color-surface-white);
  border-bottom: 1px solid #e2e8f0;
}

.toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 16px;
}

.toolbar-row-bottom {
  padding-top: 8px;
  padding-bottom: 8px;
  background: #f8fafc;
  border-top: 1px solid #f1f5f9;
}

.repo-pills {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.repo-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border-radius: var(--radius-full);
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.repo-pill:hover {
  border-color: #bae6fd;
  color: var(--color-primary-900);
}

.repo-pill.is-active {
  background: var(--color-surface-white);
  border-color: #bae6fd;
  color: var(--color-text-title);
  box-shadow: 0 1px 2px rgba(14, 165, 233, 0.08);
}

.repo-pill.is-pending {
  border-style: dashed;
}

.repo-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  flex-shrink: 0;
}

.repo-pill:not(.is-active) .repo-dot {
  opacity: 0.35;
}

.repo-name {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.repo-loc {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #94a3b8;
}

.repo-state-tag {
  padding: 1px 5px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 10px;
}

.toolbar-right-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.search-box {
  position: relative;
  width: 210px;
}

.input-icon {
  width: 14px;
  height: 14px;
  color: #94a3b8;
}

.search-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  width: 300px;
  max-height: 280px;
  overflow-y: auto;
  background: var(--color-surface-white);
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 4px;
  z-index: 40;
}

.search-hit-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  text-align: left;
  transition: background var(--transition-fast);
}

.search-hit-item:hover {
  background: var(--color-primary-50);
}

.hit-kind {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}

.hit-kind.is-module {
  background: var(--color-primary-100);
  color: var(--color-primary-700);
}

.hit-kind.is-file {
  background: #f1f5f9;
  color: #475569;
}

.hit-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.hit-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-title);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hit-path {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hit-meta {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #64748b;
  flex-shrink: 0;
}

.search-empty {
  padding: 14px 10px;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.group-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
}

.segmented-group {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border-radius: var(--radius-md);
  background: #e2e8f0;
  gap: 2px;
}

.seg-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 9px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.seg-btn:hover {
  color: var(--color-text-title);
}

.seg-btn.is-active {
  background: var(--color-surface-white);
  color: var(--color-primary-700);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.toolbar-divider {
  width: 1px;
  height: 16px;
  background: #cbd5e1;
}

.toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 9px;
  border-radius: var(--radius-md);
  border: 1px solid #e2e8f0;
  background: var(--color-surface-white);
  color: #64748b;
  font-size: 12px;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.toggle-chip:hover {
  border-color: #bae6fd;
  color: var(--color-primary-700);
}

.toggle-chip.is-active {
  background: var(--color-primary-50);
  border-color: #7dd3fc;
  color: var(--color-primary-700);
}

.chip-icon {
  width: 13px;
  height: 13px;
}

.icon-btn-group,
.zoom-group {
  display: inline-flex;
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  overflow: hidden;
}

.icon-btn,
.zoom-pct-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 26px;
  border: none;
  background: transparent;
  color: #475569;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.icon-btn {
  width: 26px;
  padding: 0;
}

.zoom-pct-btn {
  min-width: 46px;
  padding: 0 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  border-left: 1px solid #f1f5f9;
  border-right: 1px solid #f1f5f9;
}

.icon-btn:hover,
.zoom-pct-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

.btn-icon {
  width: 14px;
  height: 14px;
}

.refresh-btn {
  padding: 0 8px;
}

.is-spinning {
  animation: diorama-spin 0.9s linear infinite;
}

@keyframes diorama-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .search-box {
    width: 160px;
  }
}
</style>
