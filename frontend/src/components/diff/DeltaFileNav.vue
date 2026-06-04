<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, User, GitCompareArrows, FilePlus, FileX, FileEdit, ChevronDown, ChevronRight } from 'lucide-vue-next'
import type { HumanDeltaFileDiff, DeltaRegion, DeltaRegionSource } from '@/types/workspaceAssets'

const props = defineProps<{
  fileDiffs: HumanDeltaFileDiff[]
  deltaRegions: DeltaRegion[]
  selectedFilePath?: string | null
}>()

const emit = defineEmits<{
  'select-file': [filePath: string]
}>()

const { t } = useI18n()

type GroupKey = 'modified' | 'unchanged' | 'ai_only' | 'human_only' | 'deleted' | 'renamed' | 'rewritten'

type FileCategory = {
  key: GroupKey
  label: string
  icon: typeof Bot
  color: string
  files: HumanDeltaFileDiff[]
}

const ALL_GROUP_KEYS: GroupKey[] = ['modified', 'unchanged', 'human_only', 'deleted', 'renamed', 'rewritten', 'ai_only']

const regionIndex = computed(() => {
  const map = new Map<string, DeltaRegion[]>()
  for (const r of props.deltaRegions) {
    const arr = map.get(r.file_path)
    if (arr) arr.push(r)
    else map.set(r.file_path, [r])
  }
  return map
})

function classifyByRegions(regions: DeltaRegion[], comparisonType?: string, isUnchanged?: boolean): GroupKey {
  if (isUnchanged) return 'unchanged'
  if (comparisonType === 'common') return 'modified'

  for (const r of regions) {
    if (r.region_type === 'FILE_DELETED') return 'deleted'
    if (r.region_type === 'FILE_RENAMED') return 'renamed'
    if (r.region_type === 'FILE_REWRITTEN') return 'rewritten'
  }

  const sources = new Set(regions.map(r => r.region_source))
  if (sources.has('DIVERGED') || sources.has('BOTH_SAME')) return 'modified'
  if (sources.size === 1) {
    const only = sources.values().next().value as DeltaRegionSource
    if (only === 'AI_ONLY') return 'ai_only'
    if (only === 'HUMAN_ONLY') return 'human_only'
  }
  return 'modified'
}

const fileGroups = computed(() => {
  const grouped = new Map<GroupKey, HumanDeltaFileDiff[]>()
  for (const key of ALL_GROUP_KEYS) grouped.set(key, [])

  const diffByPath = new Map<string, HumanDeltaFileDiff>()
  for (const fd of props.fileDiffs) diffByPath.set(fd.file_path, fd)

  const classified = new Set<string>()
  for (const [filePath, regions] of regionIndex.value.entries()) {
    const diff = diffByPath.get(filePath)
    if (!diff) continue
    const allBothSame = regions.length > 0 && regions.every(r => r.region_source === 'BOTH_SAME')
    const group = classifyByRegions(regions, diff.comparison_type ?? undefined, allBothSame)
    grouped.get(group)!.push(diff)
    classified.add(filePath)
  }

  for (const fd of props.fileDiffs) {
    if (classified.has(fd.file_path)) continue
    const fallback: GroupKey =
      fd.comparison_type === 'ai_only' ? 'ai_only'
        : fd.comparison_type === 'human_only' ? 'human_only'
          : 'modified'
    grouped.get(fallback)!.push(fd)
  }

  return grouped
})

const categories = computed<FileCategory[]>(() => {
  const defs: Record<GroupKey, { label: string; icon: typeof Bot; color: string }> = {
    modified: { label: 'Modified', icon: GitCompareArrows, color: '#6366f1' },
    unchanged: { label: 'Unchanged', icon: GitCompareArrows, color: '#6b7280' },
    ai_only: { label: 'AI Only', icon: Bot, color: '#f97316' },
    human_only: { label: 'Human Only', icon: User, color: '#10b981' },
    deleted: { label: 'Deleted', icon: FileX, color: '#dc2626' },
    renamed: { label: 'Renamed', icon: FileEdit, color: '#8b5cf6' },
    rewritten: { label: 'Rewritten', icon: FilePlus, color: '#f59e0b' },
  }

  const result: FileCategory[] = []
  for (const key of ALL_GROUP_KEYS) {
    const files = fileGroups.value.get(key) ?? []
    if (files.length) {
      result.push({ key, ...defs[key], files })
    }
  }
  return result
})

const expandedCategories = ref<Set<string>>(new Set(ALL_GROUP_KEYS))

function toggleCategory(key: string) {
  if (expandedCategories.value.has(key)) {
    expandedCategories.value.delete(key)
  } else {
    expandedCategories.value.add(key)
  }
}

function regionCountForFile(filePath: string): number {
  return regionIndex.value.get(filePath)?.length ?? 0
}

function fileName(path: string): string {
  return path.split('/').pop() ?? path
}

function fileDir(path: string): string {
  const parts = path.split('/')
  return parts.length > 1 ? parts.slice(0, -1).join('/') : ''
}

type DirGroup = {
  dir: string
  files: HumanDeltaFileDiff[]
}

function groupByDir(files: HumanDeltaFileDiff[]): DirGroup[] {
  const map = new Map<string, HumanDeltaFileDiff[]>()
  for (const f of files) {
    const dir = fileDir(f.file_path)
    const arr = map.get(dir)
    if (arr) arr.push(f)
    else map.set(dir, [f])
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([dir, files]) => ({ dir, files }))
}
</script>

<template>
  <div class="delta-file-nav">
    <div class="nav-header">
      <span class="nav-title">{{ t('workspace_assets.task_detail.workbench.file_nav.title') }}</span>
      <span class="file-count">{{ fileDiffs.length }}</span>
    </div>

    <div v-for="cat in categories" :key="cat.key" class="category-group">
      <div class="category-header" @click="toggleCategory(cat.key)">
        <component :is="expandedCategories.has(cat.key) ? ChevronDown : ChevronRight" :size="14" />
        <component :is="cat.icon" :size="14" :style="{ color: cat.color }" />
        <span class="category-label">{{ cat.label }}</span>
        <span class="category-count">{{ cat.files.length }}</span>
      </div>

      <div v-if="expandedCategories.has(cat.key)" class="category-files">
        <template v-for="dirGroup in groupByDir(cat.files)" :key="dirGroup.dir">
          <div v-if="dirGroup.dir" class="dir-header">
            <span class="dir-name">{{ dirGroup.dir }}/</span>
          </div>
          <div
            v-for="file in dirGroup.files"
            :key="file.file_path"
            class="file-item"
            :class="{ 'file-selected': selectedFilePath === file.file_path }"
            @click="emit('select-file', file.file_path)"
          >
            <span class="file-name" :title="file.file_path">{{ fileName(file.file_path) }}</span>
            <span v-if="regionCountForFile(file.file_path) > 0" class="region-badge">
              {{ regionCountForFile(file.file_path) }}
            </span>
            <span class="file-stats">
              <span v-if="file.insertions" class="stat-add">+{{ file.insertions }}</span>
              <span v-if="file.deletions" class="stat-del">-{{ file.deletions }}</span>
            </span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.delta-file-nav {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  font-size: 13px;
}

.nav-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border, #e5e7eb);
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  color: var(--color-text-secondary, #6b7280);
}

.file-count {
  background: var(--color-background-muted, #f3f4f6);
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 11px;
}

.category-group {
  border-bottom: 1px solid var(--color-border-light, #f3f4f6);
}

.category-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-weight: 500;
  color: var(--color-text-primary, #374151);
}

.category-header:hover {
  background: var(--color-background-hover, #f9fafb);
}

.category-label {
  flex: 1;
}

.category-count {
  font-size: 11px;
  color: var(--color-text-secondary, #9ca3af);
}

.category-files {
  padding-bottom: 4px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 32px;
  cursor: pointer;
  color: var(--color-text-secondary, #6b7280);
}

.file-item:hover {
  background: var(--color-background-hover, #f9fafb);
}

.file-item.file-selected {
  background: var(--color-primary-light, #eff6ff);
  color: var(--color-primary, #2563eb);
}

.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
  font-size: 12px;
}

.region-badge {
  display: inline-block;
  min-width: 16px;
  height: 16px;
  line-height: 16px;
  text-align: center;
  background: var(--color-primary-light, #dbeafe);
  color: var(--color-primary, #2563eb);
  border-radius: 8px;
  font-size: 10px;
  font-weight: 600;
  padding: 0 4px;
}

.file-stats {
  display: flex;
  gap: 4px;
  font-size: 11px;
  font-family: monospace;
}

.stat-add {
  color: #16a34a;
}

.stat-del {
  color: #dc2626;
}

.dir-header {
  display: flex;
  align-items: center;
  padding: 4px 12px 2px 24px;
}

.dir-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-secondary, #9ca3af);
  letter-spacing: 0.02em;
}
</style>
