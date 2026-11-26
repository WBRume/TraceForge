<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { HandRaisedIcon } from '@heroicons/vue/24/outline'
import { ChevronDown, Download, FilePlus, FolderOpen, Layers, Link, MousePointer2, Save, Square, Trash2, Undo2 } from '@/components/icons'
import type { Arrangement, DiagramFormat, DiagramTool } from './diagramModel'

const props = defineProps<{
  title: string
  tool: DiagramTool
  undo: boolean
  redo: boolean
  saving: boolean
  selectedCount: number
  selectedEdge: boolean
  count: number
  mindMap: boolean
  organization: boolean
  snap: boolean
}>()
const emit = defineEmits<{
  rename: [value: string]
  choose: [tool: DiagramTool]
  create: []
  open: []
  save: [format: DiagramFormat]
  undo: []
  redo: []
  arrange: [arrangement: Arrangement]
  group: []
  remove: []
  snap: []
}>()
const { t } = useI18n()
const modes = [
  { id: 'select', icon: MousePointer2, key: 'V' },
  { id: 'pan', icon: HandRaisedIcon, key: 'H' },
  { id: 'connect', icon: Link, key: 'C' },
] as const
const arrangements = ['horizontal', 'vertical', 'mindmap', 'organization', 'alignLeft', 'alignTop', 'distributeX', 'distributeY'] as const

function canArrange(item: Arrangement) {
  if (item === 'mindmap' && !props.mindMap || item === 'organization' && !props.organization) return false
  if (item.startsWith('align')) return props.selectedCount >= 2
  if (item.startsWith('distribute')) return props.selectedCount >= 3
  return props.selectedCount !== 1
}

function exportDrawing(value: unknown) {
  if (value === 'svg' || value === 'png') emit('save', value)
}

function arrange(value: unknown) {
  if (arrangements.includes(value as Arrangement)) emit('arrange', value as Arrangement)
}
</script>

<template>
  <header class="diagram-toolbar">
    <div class="file-bar">
      <div class="drawing-title">
        <img class="drawing-logo" src="/favicon.svg" alt="">
        <input class="title-input" :value="title" :aria-label="t('diagram.name')" maxlength="120"
          @change="emit('rename', ($event.target as HTMLInputElement).value)" @keydown.enter="($event.target as HTMLInputElement).blur()">
      </div>
      <div class="file-actions">
        <el-button :aria-label="t('diagram.file.new')" @click="emit('create')"><FilePlus :size="16" /><span>{{ t('diagram.file.new') }}</span></el-button>
        <el-button :aria-label="t('diagram.file.open')" @click="emit('open')"><FolderOpen :size="16" /><span>{{ t('diagram.file.open') }}</span></el-button>
        <el-button type="primary" :loading="saving" :aria-label="t('diagram.file.save')" @click="emit('save', 'tfdiagram')">
          <Save :size="16" /><span>{{ t('diagram.file.save') }}</span>
        </el-button>
        <el-dropdown trigger="click" :disabled="saving || !count" @command="exportDrawing">
          <el-button :disabled="saving || !count" :aria-label="t('diagram.file.export')">
            <Download :size="16" /><span>{{ t('diagram.file.export') }}</span><ChevronDown :size="13" />
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="png">PNG</el-dropdown-item>
              <el-dropdown-item command="svg">SVG</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    <div class="edit-bar">
      <div class="edit-group" :aria-label="t('diagram.stage.label')">
        <button v-for="mode in modes" :key="mode.id" type="button" class="edit-button"
          :title="`${t('diagram.tool.' + mode.id)} (${mode.key})`" :aria-label="t('diagram.tool.' + mode.id)"
          :aria-pressed="tool === mode.id" @click="emit('choose', mode.id)"><component :is="mode.icon" class="edit-icon" /></button>
      </div>
      <div class="edit-group">
        <button type="button" class="edit-button" :title="t('diagram.tool.undo')" :aria-label="t('diagram.tool.undo')"
          :disabled="!undo" @click="emit('undo')"><Undo2 class="edit-icon" /></button>
        <button type="button" class="edit-button redo" :title="t('diagram.tool.redo')" :aria-label="t('diagram.tool.redo')"
          :disabled="!redo" @click="emit('redo')"><Undo2 class="edit-icon" /></button>
      </div>
      <div class="edit-group">
        <button type="button" class="edit-button" :title="t('diagram.tool.group')" :aria-label="t('diagram.tool.group')"
          :disabled="!selectedCount" @click="emit('group')"><Square class="edit-icon" /></button>
        <button type="button" class="edit-button" :title="t('diagram.tool.delete')" :aria-label="t('diagram.tool.delete')"
          :disabled="!selectedCount && !selectedEdge" @click="emit('remove')"><Trash2 class="edit-icon" /></button>
        <el-dropdown trigger="click" :disabled="count < 2" @command="arrange">
          <button type="button" class="edit-button arrange-button" :disabled="count < 2">
            <Layers class="edit-icon" />{{ t('diagram.tool.layout') }}<ChevronDown :size="12" />
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="item in arrangements" :key="item" :command="item" :divided="item === 'alignLeft'"
                :disabled="!canArrange(item)">{{ t('diagram.tool.' + item) }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <label class="snap-toggle">
        <el-switch :model-value="snap" size="small" :aria-label="t('diagram.tool.snap')" @change="emit('snap')" />
        <span>{{ t('diagram.tool.snap') }}</span>
      </label>
    </div>
  </header>
</template>

<style scoped>
.diagram-toolbar { background: #fff; border-bottom: 1px solid #dfe7f0; z-index: 1; }
.file-bar, .edit-bar { display: flex; align-items: center; gap: 12px; padding: 0 16px; }
.file-bar { height: 59px; justify-content: space-between; border-bottom: 1px solid #eef2f6; }
.drawing-title { min-width: 120px; display: flex; align-items: center; gap: 8px; flex: 1; }
.drawing-logo { width: 24px; height: 24px; }
.title-input { width: min(100%, 390px); min-width: 0; padding: 5px 7px; color: #142e49; border: 1px solid transparent; border-radius: 6px; font-size: 16px; font-weight: 690; background: transparent; }
.title-input:is(:hover, :focus) { border-color: #cbdced; }
.file-actions { display: flex; gap: 7px; }
.file-actions :deep(.el-button) { margin: 0; }
.file-actions :deep(.el-button > span) { display: inline-flex; align-items: center; gap: 6px; }
.edit-bar { height: 42px; gap: 8px; }
.edit-group { display: flex; gap: 3px; padding-right: 7px; border-right: 1px solid #e5edf4; }
.edit-button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 30px; height: 29px; padding: 0 5px; border: 0; border-radius: 5px; background: transparent; color: #3c5570; font-size: 12px; cursor: pointer; }
.edit-button:not(:disabled):hover { background: #edf5fb; }
.edit-button[aria-pressed="true"] { background: #e0f2fe; color: #0369a1; }
.edit-button:disabled { color: #aab8c7; cursor: default; }
.edit-icon { width: 17px; height: 17px; }
.redo .edit-icon { transform: scaleX(-1); }
.snap-toggle { display: inline-flex; align-items: center; gap: 6px; color: #516a84; font-size: 12px; }
@media (max-width: 820px) { .file-bar, .edit-bar { padding: 0 10px; } .file-actions { gap: 4px; } }
</style>
