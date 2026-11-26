<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { HandRaisedIcon } from '@heroicons/vue/24/outline'
import { ChevronDown, Download, FilePlus, FolderOpen, Layers, Link, MousePointer2, PencilLine, Square, Trash2, Undo2 } from '@/components/icons'
import DiagramActionHint from './DiagramActionHint.vue'
import { diagramCommandKeys, diagramDeleteKeys, diagramToolKeys } from './diagramKeyBindings'
import type { Arrangement, DiagramTool } from './diagramModel'

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
  export: []
  undo: []
  redo: []
  arrange: [arrangement: Arrangement]
  group: []
  remove: []
  clearCanvas: []
  snap: []
}>()
const { t } = useI18n()
const modifier = /mac/i.test(navigator.platform) ? 'Meta' : 'Control'
const commandKey = (key: string, shift = false) => `${modifier}+${shift ? 'Shift+' : ''}${key.toUpperCase()}`
const shortcuts = {
  open: [commandKey(diagramCommandKeys.open)],
  export: [commandKey(diagramCommandKeys.export)],
  undo: [commandKey(diagramCommandKeys.undo)],
  redo: [commandKey(diagramCommandKeys.redo), commandKey(diagramCommandKeys.undo, true)],
  remove: diagramDeleteKeys,
}
const modes = ([
  { id: 'select', icon: MousePointer2 },
  { id: 'pan', icon: HandRaisedIcon },
  { id: 'connect', icon: Link },
  { id: 'sketch', icon: PencilLine },
] as const).map(mode => ({ ...mode, key: diagramToolKeys[mode.id].toUpperCase() }))
const arrangements = ['horizontal', 'vertical', 'mindmap', 'organization', 'alignLeft', 'alignTop', 'distributeX', 'distributeY'] as const

function canArrange(item: Arrangement) {
  if (item === 'mindmap' && !props.mindMap || item === 'organization' && !props.organization) return false
  if (item.startsWith('align')) return props.selectedCount >= 2
  if (item.startsWith('distribute')) return props.selectedCount >= 3
  return props.selectedCount !== 1
}

function arrange(value: unknown) {
  if (arrangements.includes(value as Arrangement)) emit('arrange', value as Arrangement)
}
</script>

<template>
  <header class="diagram-toolbar">
    <div class="file-bar">
      <div class="drawing-title">
        <input class="title-input" :value="title" :aria-label="t('diagram.name')" maxlength="120"
          @change="emit('rename', ($event.target as HTMLInputElement).value)" @keydown.enter="($event.target as HTMLInputElement).blur()">
      </div>
      <div class="file-actions">
        <DiagramActionHint :label="t('diagram.file.new')">
          <el-button :aria-label="t('diagram.file.new')" @click="emit('create')">
            <FilePlus :size="16" /><span>{{ t('diagram.file.new') }}</span>
          </el-button>
        </DiagramActionHint>
        <DiagramActionHint :label="t('diagram.file.open')" :shortcuts="shortcuts.open">
          <el-button :aria-label="t('diagram.file.open')" :aria-keyshortcuts="shortcuts.open.join(' ')" @click="emit('open')">
            <FolderOpen :size="16" /><span>{{ t('diagram.file.open') }}</span>
          </el-button>
        </DiagramActionHint>
        <DiagramActionHint :label="t('diagram.file.export')" :shortcuts="shortcuts.export">
          <el-button type="primary" :loading="saving" :aria-label="t('diagram.file.export')"
            :aria-keyshortcuts="shortcuts.export.join(' ')" @click="emit('export')">
            <Download :size="16" /><span>{{ t('diagram.file.export') }}</span>
          </el-button>
        </DiagramActionHint>
      </div>
    </div>
    <div class="edit-bar">
      <div class="edit-group" :aria-label="t('diagram.stage.label')">
        <DiagramActionHint v-for="mode in modes" :key="mode.id" :label="t('diagram.tool.' + mode.id)" :shortcuts="[mode.key]">
          <button type="button" class="edit-button" :aria-label="t('diagram.tool.' + mode.id)" :aria-keyshortcuts="mode.key"
            :aria-pressed="tool === mode.id" @click="emit('choose', mode.id)"><component :is="mode.icon" class="edit-icon" /></button>
        </DiagramActionHint>
      </div>
      <div class="edit-group">
        <DiagramActionHint :label="t('diagram.tool.undo')" :shortcuts="shortcuts.undo">
          <button type="button" class="edit-button" :aria-label="t('diagram.tool.undo')" :aria-keyshortcuts="shortcuts.undo.join(' ')"
            :disabled="!undo" @click="emit('undo')"><Undo2 class="edit-icon" /></button>
        </DiagramActionHint>
        <DiagramActionHint :label="t('diagram.tool.redo')" :shortcuts="shortcuts.redo">
          <button type="button" class="edit-button redo" :aria-label="t('diagram.tool.redo')" :aria-keyshortcuts="shortcuts.redo.join(' ')"
            :disabled="!redo" @click="emit('redo')"><Undo2 class="edit-icon" /></button>
        </DiagramActionHint>
      </div>
      <div class="edit-group">
        <DiagramActionHint :label="t('diagram.tool.group')">
          <button type="button" class="edit-button" :aria-label="t('diagram.tool.group')"
            :disabled="!selectedCount" @click="emit('group')"><Square class="edit-icon" /></button>
        </DiagramActionHint>
        <DiagramActionHint :label="t('diagram.tool.delete')" :shortcuts="shortcuts.remove">
          <button type="button" class="edit-button" :aria-label="t('diagram.tool.delete')" :aria-keyshortcuts="shortcuts.remove.join(' ')"
            :disabled="!selectedCount && !selectedEdge" @click="emit('remove')"><Trash2 class="edit-icon" /></button>
        </DiagramActionHint>
        <DiagramActionHint :label="t('diagram.tool.clearCanvas')">
          <button type="button" class="edit-button" :disabled="!count || saving" @click="emit('clearCanvas')">
            {{ t('diagram.tool.clearCanvas') }}
          </button>
        </DiagramActionHint>
        <DiagramActionHint :label="t('diagram.tool.layout')">
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
        </DiagramActionHint>
      </div>
      <DiagramActionHint :label="t('diagram.tool.snap')">
        <label class="snap-toggle">
          <el-switch :model-value="snap" size="small" :aria-label="t('diagram.tool.snap')" @change="emit('snap')" />
          <span>{{ t('diagram.tool.snap') }}</span>
        </label>
      </DiagramActionHint>
    </div>
  </header>
</template>

<style scoped>
.diagram-toolbar { display: grid; gap: 10px; background: var(--color-surface-white); }
.file-bar, .edit-bar { display: flex; align-items: center; gap: 12px; }
.file-bar { min-height: 38px; justify-content: space-between; }
.drawing-title { min-width: 120px; display: flex; align-items: center; gap: 8px; flex: 1; }
.title-input { width: min(100%, 390px); min-width: 0; padding: 5px 8px; color: var(--color-text-title); border: 1px solid transparent; border-radius: var(--radius-md); font: 650 18px var(--font-heading); background: transparent; }
.title-input:hover { border-color: var(--diagram-border); }
.title-input:focus { outline: none; border-color: var(--color-primary-500); }
.file-actions { display: flex; gap: 7px; }
.file-actions :deep(.el-button) { margin: 0; }
.file-actions :deep(.el-button > span) { display: inline-flex; align-items: center; gap: 6px; }
.edit-bar { min-height: 42px; gap: 8px; padding: 3px 8px; border: 1px solid var(--diagram-border); border-radius: var(--radius-md); background: var(--color-bg-base); }
.edit-group { display: flex; gap: 3px; padding-right: 7px; border-right: 1px solid var(--diagram-border); }
.edit-button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 30px; height: 29px; padding: 0 5px; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--color-text-body); font-size: 12px; cursor: pointer; }
.edit-button:not(:disabled):hover, .edit-button:focus-visible { background: var(--color-primary-50); color: var(--color-primary-700); }
.edit-button[aria-pressed="true"] { background: var(--color-primary-100); color: var(--color-primary-700); }
.edit-button:disabled { opacity: .42; cursor: default; }
.edit-icon { width: 17px; height: 17px; }
.redo .edit-icon { transform: scaleX(-1); }
.snap-toggle { display: inline-flex; align-items: center; gap: 6px; color: var(--color-text-muted); font-size: 12px; --el-switch-on-color: var(--color-primary-500); }
@media (max-width: 820px) { .file-actions { gap: 4px; } }
</style>
