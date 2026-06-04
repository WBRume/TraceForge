<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, User, GitCompareArrows, ChevronDown, ChevronRight } from 'lucide-vue-next'
import MonacoDiffViewer from '@/components/diff/MonacoDiffViewer.vue'
import SideBySideHunkViewer from '@/components/diff/SideBySideHunkViewer.vue'
import type { HumanDeltaFileDiff, DeltaRegion } from '@/types/workspaceAssets'

const props = defineProps<{
  fileDiffs: HumanDeltaFileDiff[]
  deltaRegions?: DeltaRegion[]
  selectedFilePath?: string | null
}>()

const emit = defineEmits<{
  'range-select': [payload: { filePath: string; lineStart: number; lineEnd: number; source: string; selectedText: string }]
}>()

const { t } = useI18n()

const displayFileDiffs = computed(() => {
  if (props.selectedFilePath) {
    return props.fileDiffs.filter(f => f.file_path === props.selectedFilePath)
  }
  return []
})

const aiOnlyCount = computed(() => displayFileDiffs.value.filter(f => f.comparison_type === 'ai_only').length)
const humanOnlyCount = computed(() => displayFileDiffs.value.filter(f => f.comparison_type === 'human_only').length)
const commonCount = computed(() => displayFileDiffs.value.filter(f => f.comparison_type === 'common').length)

type FileGroup = {
  type: 'ai_only' | 'human_only' | 'common' | 'unchanged'
  label: string
  icon: typeof Bot
  color: string
  files: HumanDeltaFileDiff[]
}

function isFileUnchanged(file: HumanDeltaFileDiff): boolean {
  const regions = (props.deltaRegions ?? []).filter(r => r.file_path === file.file_path)
  return regions.length > 0 && regions.every(r => r.region_source === 'BOTH_SAME')
}

const groupedFiles = computed<FileGroup[]>(() => {
  const groups: FileGroup[] = [
    {
      type: 'common',
      label: t('workspace_assets.task_detail.workbench.diff_filter.common'),
      icon: GitCompareArrows,
      color: '#94a3b8',
      files: displayFileDiffs.value.filter(f => f.comparison_type === 'common' && !isFileUnchanged(f)),
    },
    {
      type: 'unchanged',
      label: 'Unchanged',
      icon: GitCompareArrows,
      color: '#6b7280',
      files: displayFileDiffs.value.filter(f => f.comparison_type === 'common' && isFileUnchanged(f)),
    },
    {
      type: 'ai_only',
      label: t('workspace_assets.task_detail.workbench.diff_filter.ai_only'),
      icon: Bot,
      color: '#f97316',
      files: displayFileDiffs.value.filter(f => f.comparison_type === 'ai_only'),
    },
    {
      type: 'human_only',
      label: t('workspace_assets.task_detail.workbench.diff_filter.human_only'),
      icon: User,
      color: '#10b981',
      files: displayFileDiffs.value.filter(f => f.comparison_type === 'human_only'),
    },
  ]
  return groups.filter(g => g.files.length > 0)
})

const collapsedFiles = ref<Set<string>>(new Set())

function toggleFile(path: string) {
  if (collapsedFiles.value.has(path)) {
    collapsedFiles.value.delete(path)
  } else {
    collapsedFiles.value.add(path)
  }
}

function isCollapsed(path: string) {
  return collapsedFiles.value.has(path)
}

function onMonacoRangeSelect(filePath: string, payload: { lineStart: number; lineEnd: number; side: string; selectedText: string }) {
  emit('range-select', {
    filePath,
    lineStart: payload.lineStart,
    lineEnd: payload.lineEnd,
    source: payload.side,
    selectedText: payload.selectedText,
  })
}

// ── Scroll to file ──
function scrollToFile(filePath: string) {
  const el = document.getElementById(`file-${CSS.escape(filePath)}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

defineExpose({ scrollToFile })

watch(() => displayFileDiffs.value, () => {
  collapsedFiles.value = new Set()
})

watch(() => props.selectedFilePath, (path) => {
  if (path) {
    collapsedFiles.value.delete(path)
  }
})
</script>

<template>
  <div class="patch-compare">
    <!-- Summary -->
    <div class="compare-summary">
      <span v-if="aiOnlyCount" class="summary-badge ai-only">
        <Bot :size="12" />
        {{ aiOnlyCount }} {{ t('workspace_assets.task_detail.workbench.diff_filter.ai_only') }}
      </span>
      <span v-if="humanOnlyCount" class="summary-badge human-only">
        <User :size="12" />
        {{ humanOnlyCount }} {{ t('workspace_assets.task_detail.workbench.diff_filter.human_only') }}
      </span>
      <span v-if="commonCount" class="summary-badge common">
        <GitCompareArrows :size="12" />
        {{ commonCount }} {{ t('workspace_assets.task_detail.workbench.diff_filter.common') }}
      </span>
    </div>

    <!-- File groups -->
    <div v-if="!selectedFilePath" class="select-file-hint">
      <GitCompareArrows :size="24" />
      <span>{{ t('workspace_assets.task_detail.workbench.diff_filter.select_file_hint') }}</span>
    </div>
    <div v-else class="compare-content">
      <template v-for="group in groupedFiles" :key="group.type">
        <!-- Group header -->
        <div class="group-header" :style="{ color: group.color }">
          <component :is="group.icon" :size="14" />
          <span class="group-label">{{ group.label }}</span>
          <span class="group-count">{{ group.files.length }} {{ t('workspace_assets.task_detail.workbench.diff_filter.files') }}</span>
          <span class="group-line"></span>
        </div>

        <!-- Files -->
        <template v-for="file in group.files" :key="file.file_path">
          <!-- File header -->
          <div :id="'file-' + file.file_path" class="file-header" @click="toggleFile(file.file_path)">
            <span class="file-toggle">
              <ChevronDown v-if="!isCollapsed(file.file_path)" :size="14" />
              <ChevronRight v-else :size="14" />
            </span>
            <span class="file-name">{{ file.file_path }}</span>
            <span v-if="group.type === 'common'" class="file-stats-split">
              <span class="stat-ai">AI: +{{ file.ai_insertions }} -{{ file.ai_deletions }}</span>
              <span class="stat-sep">|</span>
              <span class="stat-human">Human: +{{ file.human_insertions }} -{{ file.human_deletions }}</span>
            </span>
            <span v-else class="file-stats">
              <span class="stat-add">+{{ file.insertions }}</span>
              <span class="stat-del">-{{ file.deletions }}</span>
            </span>
          </div>

          <!-- Diff content -->
          <div v-if="!isCollapsed(file.file_path)" class="file-diff">
            <!-- Common/Modified/Unchanged: side-by-side diff (AI Output vs Human Output) -->
            <template v-if="group.type === 'common' || group.type === 'unchanged'">
              <SideBySideHunkViewer
                :hunks="file.hunks ?? []"
                @range-select="(p) => onMonacoRangeSelect(file.file_path, p)"
              />
            </template>

            <!-- AI-only / Human-only / Deleted / Renamed / Rewritten: Monaco diff with one side -->
            <template v-else>
              <MonacoDiffViewer
                :ai-hunks="group.type === 'ai_only' ? (file.ai_hunks ?? []) : []"
                :human-hunks="group.type === 'human_only' ? (file.human_hunks ?? []) : []"
                @range-select="(p) => onMonacoRangeSelect(file.file_path, p)"
              />
            </template>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.patch-compare {
  display: flex;
  flex-direction: column;
  background: #0f172a;
  border-radius: 8px;
  font-family: var(--font-mono, 'Consolas', 'Monaco', monospace);
  font-size: 0.8125rem;
  line-height: 1.5;
  overflow: hidden;
  height: 100%;
}

/* ── Summary ── */
.compare-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
}

.summary-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.75rem;
  font-weight: 600;
}

.summary-badge.ai-only { color: #f97316; }
.summary-badge.human-only { color: #10b981; }
.summary-badge.common { color: #94a3b8; }

/* ── Content ── */
.compare-content {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}

/* ── Group header ── */
.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: rgba(255, 255, 255, 0.03);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  position: sticky;
  top: 0;
  z-index: 3;
}

.group-count {
  font-weight: 500;
  opacity: 0.6;
  font-size: 0.7rem;
}

.group-line {
  flex: 1;
  height: 1px;
  background: currentColor;
  opacity: 0.15;
}

/* ── File header ── */
.file-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.04);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  cursor: pointer;
  user-select: none;
  font-weight: 600;
  color: #e2e8f0;
  position: sticky;
  top: 37px;
  z-index: 2;
}

.file-header:hover {
  background: rgba(255, 255, 255, 0.06);
}

.file-toggle {
  color: #64748b;
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.file-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8125rem;
}

.file-stats, .file-stats-split {
  display: flex;
  gap: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  flex-shrink: 0;
  align-items: center;
}

.stat-add { color: #10b981; }
.stat-del { color: #f43f5e; }
.stat-ai { color: #fb923c; }
.stat-human { color: #34d399; }
.stat-sep { color: #334155; }

/* ── File diff ── */
.file-diff {
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  min-height: 400px;
  max-height: calc(100vh - 200px);
}

.select-file-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 24px;
  color: #475569;
  font-size: 0.8125rem;
  text-align: center;
}
</style>
