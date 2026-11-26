<script setup lang="ts">
import { computed, nextTick, onMounted, onScopeDispose, shallowRef, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { DiagramWindowApi } from '@/types/diagramDesktop'
import DiagramToolbar from './DiagramToolbar.vue'
import DiagramTitleBar from './DiagramTitleBar.vue'
import DiagramExportDialog from './DiagramExportDialog.vue'
import DiagramPalette from './DiagramPalette.vue'
import DiagramStage from './DiagramStage.vue'
import DiagramInspector from './DiagramInspector.vue'
import DiagramTemplateDialog from './DiagramTemplateDialog.vue'
import { diagramFile } from './diagramExport'
import { blankDiagram, decodeDiagram, GRID, MAX_FILE_BYTES,
  type Arrangement, type DiagramDocument, type DiagramFormat, type DiagramTool, type Shape } from './diagramModel'
import { createTemplate, type DiagramTemplate } from './diagramTemplates'
import { useDiagramDocument } from './useDiagramDocument'
import type { Point } from '@/utils/canvasViewport'

const props = defineProps<{ native: DiagramWindowApi }>()
const { t, locale } = useI18n()
const untitled = t('diagram.untitled')
const editor = useDiagramDocument(untitled)
const { doc, selection, selectedNodes, selectedEdge, canUndo, canRedo, dirty, persisted } = editor
const stage = useTemplateRef<InstanceType<typeof DiagramStage>>('stage')
const inspector = useTemplateRef<InstanceType<typeof DiagramInspector>>('inspector')
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const tool = shallowRef<DiagramTool>('select')
const pending = shallowRef<Shape | null>(null)
const snap = shallowRef(true)
const saving = shallowRef(false)
const exportOpen = shallowRef(false)
const templates = shallowRef(false)
const replacement = shallowRef<{ doc: DiagramDocument; file: boolean }>()
const dialogOpen = computed(() => templates.value || !!replacement.value || exportOpen.value)
const mindMap = computed(() => doc.value.edges.some(edge => edge.relation === 'branch'))
const organization = computed(() => doc.value.edges.some(edge => edge.relation === 'reporting'))

function choose(value: DiagramTool) {
  pending.value = null
  tool.value = value
  stage.value?.cancel()
  stage.value?.focus()
}

function place(shape: Shape, point: Point) {
  editor.addNode(shape, point, shape === 'initial' || shape === 'final' ? '' : t('diagram.shapes.' + shape))
  choose('select')
}

function selectShape(shape: Shape) {
  tool.value = 'select'
  pending.value = shape
  stage.value?.focus()
}

async function save(format: DiagramFormat): Promise<boolean> {
  if (saving.value) return false
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  saving.value = true
  await nextTick()
  const snapshot = doc.value
  try {
    const request = await diagramFile(snapshot, format, () => stage.value!.exportSvg())
    const result = await props.native.save(request)
    if (result.saved) {
      if (format === 'tfdiagram') editor.markSaved(snapshot)
      ElMessage.success(t('diagram.file.saved'))
      return true
    }
    if (!result.canceled) ElMessage.error(t('diagram.file.saveError'))
  } catch (error) {
    ElMessage.error(t(String(error).includes('DIAGRAM_PNG_SIZE') ? 'diagram.file.tooLarge' : 'diagram.file.saveError'))
  } finally {
    saving.value = false
  }
  return false
}

function openExport() {
  if (!saving.value) exportOpen.value = true
}

async function exportDrawing(format: DiagramFormat) {
  if (await save(format)) exportOpen.value = false
}

async function replace(next: DiagramDocument, fromFile = false) {
  if (saving.value) return
  if (dirty.value) { replacement.value = { doc: next, file: fromFile }; return }
  await applyReplacement(next, fromFile)
}

async function applyReplacement(next: DiagramDocument, fromFile: boolean) {
  replacement.value = undefined
  editor.replace(next, fromFile)
  choose('select')
  await nextTick()
  stage.value?.fit()
}

async function confirmReplacement(saveFirst: boolean) {
  const next = replacement.value
  if (next && (!saveFirst || await save('tfdiagram'))) await applyReplacement(next.doc, next.file)
}

async function readFile(file: File) {
  try {
    if (file.size > MAX_FILE_BYTES) throw new Error('Drawing is too large')
    await replace(decodeDiagram(await file.text()), true)
  } catch { ElMessage.error(t('diagram.file.loadError')) }
}

function open(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void readFile(file)
}

function fromTemplate(template: DiagramTemplate) {
  templates.value = false
  void replace(createTemplate(template, t('diagram.templates.' + template), locale.value === 'zh'))
}

async function arrange(arrangement: Arrangement) {
  editor.arrange(arrangement)
  if (arrangement === 'horizontal' || arrangement === 'vertical' || arrangement === 'mindmap' || arrangement === 'organization') {
    await nextTick()
    stage.value?.fit()
  }
}

function editable(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest('input, textarea, select, [contenteditable="true"]'))
}

function clipboardCopy(event: ClipboardEvent) {
  if (editable(event.target) || dialogOpen.value) return
  const doc = editor.extractedSelection()
  if (!doc.nodes.length || !event.clipboardData) return
  event.preventDefault()
  event.clipboardData.setData('text/plain', JSON.stringify(doc))
}

function clipboardPaste(event: ClipboardEvent) {
  if (editable(event.target) || dialogOpen.value) return
  const payload = event.clipboardData?.getData('text/plain')
  if (!payload) return
  try {
    editor.paste(decodeDiagram(payload))
    event.preventDefault()
  } catch { /* The clipboard can contain content from other apps. */ }
}

function keyDown(event: KeyboardEvent) {
  if (event.isComposing || dialogOpen.value) return
  const key = event.key.toLowerCase()
  if ((event.ctrlKey || event.metaKey) && key === 's') {
    event.preventDefault()
    openExport()
    return
  }
  if (editable(event.target) || (event.target instanceof Element && event.target.closest('[role="menu"], [role="combobox"]'))) return
  const command = event.ctrlKey || event.metaKey
  if (command && key === 'z') {
    event.preventDefault()
    if (event.shiftKey) editor.redo()
    else editor.undo()
  } else if (command && key === 'y') {
    event.preventDefault()
    editor.redo()
  } else if (command && key === 'a') {
    event.preventDefault()
    editor.selectNodes(doc.value.nodes.map(node => node.id))
  } else if (command && key === 'd') {
    event.preventDefault()
    editor.paste(editor.extractedSelection())
  } else if (command && key === 'o') {
    event.preventDefault()
    fileInput.value?.click()
  } else if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault()
    editor.remove()
  } else if (event.key === 'Escape') {
    choose('select')
    editor.selectNodes([])
  } else if (!command && !event.altKey && key === 'v') choose('select')
  else if (!command && !event.altKey && key === 'h') choose('pan')
  else if (!command && !event.altKey && key === 'c') choose('connect')
  else if (event.key === 'Enter' && event.target instanceof SVGSVGElement) inspector.value?.focusLabel()
  else if (event.key.startsWith('Arrow') && selectedNodes.value.length && event.target instanceof SVGSVGElement) {
    event.preventDefault()
    const step = event.shiftKey ? 1 : snap.value ? GRID : 4
    editor.nudge(key === 'arrowleft' ? -step : key === 'arrowright' ? step : 0,
      key === 'arrowup' ? -step : key === 'arrowdown' ? step : 0)
  }
}

onMounted(() => {
  window.addEventListener('keydown', keyDown)
  window.addEventListener('copy', clipboardCopy)
  window.addEventListener('paste', clipboardPaste)
})
onScopeDispose(() => {
  window.removeEventListener('keydown', keyDown)
  window.removeEventListener('copy', clipboardCopy)
  window.removeEventListener('paste', clipboardPaste)
})
</script>

<template>
  <div class="diagram-window">
    <DiagramTitleBar v-if="native.chrome" :chrome="native.chrome" />
    <main class="diagram-workbench" data-testid="diagram-workbench">
      <DiagramToolbar :title="doc.title" :tool="tool" :undo="canUndo" :redo="canRedo" :saving="saving"
        :selected-count="selectedNodes.length" :selected-edge="!!selectedEdge" :count="doc.nodes.length" :snap="snap"
        :mind-map="mindMap" :organization="organization"
        @rename="editor.rename" @choose="choose" @create="replace(blankDiagram(untitled))" @open="fileInput?.click()"
        @export="openExport" @undo="editor.undo" @redo="editor.redo" @arrange="arrange" @group="editor.groupSelection(t('diagram.shapes.frame'))"
        @remove="editor.remove" @snap="snap = !snap" />
      <div class="diagram-body">
        <DiagramPalette :pending="pending" @choose="selectShape" @templates="templates = true" />
        <DiagramStage ref="stage" :doc="doc" :tool="tool" :pending="pending" :snap="snap"
          :selected="selection.nodes" :selected-edge="selection.edge" @place="place" @select="editor.selectNodes"
          @edge="editor.selectEdge" @join="editor.addEdge" @update="editor.updateNodes" @open-file="readFile" />
        <DiagramInspector ref="inspector" :nodes="selectedNodes" :edge="selectedEdge" @update-node="editor.updateNode" @update-edge="editor.updateEdge" />
      </div>
      <footer class="diagram-status">
        <span>{{ t('diagram.stage.count', { nodes: doc.nodes.length, edges: doc.edges.length }) }}</span>
        <span class="draft-status" :class="{ failed: !persisted }" role="status">{{ t(persisted ? 'diagram.local' : 'diagram.draftError') }}</span>
      </footer>
      <input ref="fileInput" type="file" accept=".tfdiagram,.json" data-testid="diagram-file-input" hidden @change="open">
      <DiagramTemplateDialog v-if="templates" @close="templates = false" @select="fromTemplate" />
      <DiagramExportDialog v-if="exportOpen" :saving="saving" :has-artwork="doc.nodes.length > 0"
        @close="exportOpen = false" @submit="exportDrawing" />
      <el-dialog v-if="replacement" :model-value="true" :title="t('diagram.templates.replace')" width="min(510px, 95vw)"
        :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving" append-to-body @close="replacement = undefined">
        <p>{{ t('diagram.templates.note') }}</p>
        <template #footer>
          <el-button :disabled="saving" @click="replacement = undefined">{{ t('diagram.tool.cancel') }}</el-button>
          <el-button :disabled="saving" @click="confirmReplacement(false)">{{ t('diagram.templates.replace') }}</el-button>
          <el-button type="primary" :loading="saving" @click="confirmReplacement(true)">{{ t('diagram.templates.saveFirst') }}</el-button>
        </template>
      </el-dialog>
    </main>
  </div>
</template>

<style scoped>
.diagram-window { --diagram-border: #e2e8f0; display: flex; flex-direction: column; height: 100dvh; background: var(--color-bg-base); color: var(--color-text-body); }
.diagram-workbench { flex: 1; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 12px; margin: 10px; padding: 14px; border: 1px solid var(--diagram-border); border-radius: var(--radius-lg); background: var(--color-surface-white); box-shadow: var(--shadow-sm); }
.diagram-body { display: grid; grid-template-columns: 194px minmax(0, 1fr) 226px; gap: 10px; min-height: 0; min-width: 0; }
.diagram-status { display: flex; justify-content: space-between; align-items: center; gap: 12px; color: var(--color-text-muted); font-size: 11px; }
.draft-status { display: inline-flex; align-items: center; gap: 6px; }
.draft-status::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--color-accent-emerald); }
.draft-status.failed::before { background: var(--color-accent-rose); }
@media (max-width: 960px) {
  .diagram-workbench { margin: 8px; padding: 10px; }
  .diagram-body { grid-template-columns: 154px minmax(0, 1fr) 180px; }
}
</style>
