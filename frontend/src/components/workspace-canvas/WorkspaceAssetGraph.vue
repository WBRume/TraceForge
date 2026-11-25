<script setup lang="ts">
import { computed, onMounted, shallowRef, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { LayoutGrid, RefreshCw, Workflow, X } from '@/components/icons'
import { useWorkspaceContext } from '@/composables/chat/tasklist/useWorkspaceContext'
import { useProvisioningStore } from '@/stores/provisioning'
import type { RequirementTaskRelation } from '@/types/workspaceAssets'
import api from '@/utils/api'
import CanvasAssetCommands from './CanvasAssetCommands.vue'
import CanvasAssetCreation from './CanvasAssetCreation.vue'
import CanvasAssetSearch from './CanvasAssetSearch.vue'
import CanvasParagraphPicker from './CanvasParagraphPicker.vue'
import CanvasRelationEditor from './CanvasRelationEditor.vue'
import CanvasStage from './CanvasStage.vue'
import CanvasTextEditor from './CanvasTextEditor.vue'
import { layoutWorkspaceAssets, paragraphPosition } from './assetLayout'
import { frameMembers } from './geometry'
import { assetOperation, canvasId, isDocument, nodeInput, nodeSizes, referenceKey, sourceIcons, sourceKinds,
  type CanvasCommand, type CanvasConnection, type CanvasNode, type CanvasRelation, type CanvasSelection,
  type NodePatch, type Point, type SourceItem, type SourceKind } from './model'
import { useWorkspaceCanvas } from './useWorkspaceCanvas'

const props = defineProps<{ workspaceId: string }>()
const { t } = useI18n()
const router = useRouter()
const stage = useTemplateRef<InstanceType<typeof CanvasStage>>('stage')
const assetCreation = useTemplateRef<InstanceType<typeof CanvasAssetCreation>>('assetCreation')
const selection = shallowRef<CanvasSelection | null>(null)
const focusedKind = shallowRef<SourceKind | null>(null)
const editorId = shallowRef('')
const paragraphId = shallowRef('')
const selectedRelation = shallowRef<Pick<CanvasRelation, 'requirement_id' | 'task_id'> | null>(null)
const context = useWorkspaceContext({ getWorkspaceId: () => props.workspaceId })
const jobs = useProvisioningStore()
const { snapshot, planFiles, readingPlans, loading, saving, syncError, saveError, canRetry, refresh, edit, retry, submit } =
  useWorkspaceCanvas(props.workspaceId)

onMounted(() => { void context.loadWorkspace().catch(() => {}) })
watch(() => jobs.taskListRefreshToken, () => { void refresh(true) })
const graph = computed(() => snapshot.value && layoutWorkspaceAssets(snapshot.value, planFiles.value))
const nodes = computed(() => graph.value?.nodes || [])
const nodesById = computed(() => new Map(nodes.value.map(node => [node.id, node])))
const savedIds = computed(() => new Set(snapshot.value?.nodes.map(node => node.id)))
const editor = computed(() => nodesById.value.get(editorId.value))
const access = computed(() => graph.value?.access.source_kinds ?? [])
const tasks = computed(() => snapshot.value?.assets.filter(item => item.reference.kind === 'task') ?? [])
const canUpload = computed(() => Boolean(context.workspacePermissions.value?.upload_task_spec && tasks.value.length))
const groups = computed(() => sourceKinds.filter(kind => access.value.includes(kind) && kind !== 'plan_document'))
const relation = computed(() => {
  const link = selectedRelation.value
  return link ? graph.value?.relations.find(row => row.requirement_id === link.requirement_id && row.task_id === link.task_id) : undefined
})
const relatedRequirement = computed(() => nodes.value.find(node =>
  node.reference?.kind === 'requirement' && node.reference.id === relation.value?.requirement_id)?.details)
const relatedTask = computed(() => nodes.value.find(node =>
  node.reference?.kind === 'task' && node.reference.id === relation.value?.task_id)?.details)
const paragraphSource = computed(() => {
  const node = nodesById.value.get(paragraphId.value)
  return node?.details && node.reference && isDocument(node.reference) && !node.reference.block
    ? { title: node.details.title, reference: node.reference } : null
})
const syncLabel = computed(() => t(saving.value ? 'workspace_canvas.saving' : syncError.value
  ? 'workspace_canvas.sync_paused' : readingPlans.value ? 'workspace_canvas.plan_loading' : 'workspace_canvas.synced'))

watch(graph, next => {
  const current = selection.value
  if (current && !next?.[current.type === 'node' ? 'nodes' : 'edges'].some(item => item.id === current.id)) selection.value = null
  if (editorId.value && !editor.value) editorId.value = ''
  if (paragraphId.value && !paragraphSource.value) paragraphId.value = ''
})

function focusKind(kind: SourceKind | null) {
  focusedKind.value = kind
  if (!kind) { stage.value?.fit(); return }
  const items = nodes.value.filter(node => node.reference?.kind === kind
    || (kind === 'document' && node.reference?.kind === 'plan_document'))
  if (!items.length) { ElMessage.info(t('workspace_canvas.no_results')); return }
  stage.value?.focusNodes(items.map(node => node.id))
}

function command(action: CanvasCommand) {
  selectedRelation.value = null
  assetCreation.value?.open(action)
}

async function create(kind: CanvasNode['kind'], position: Point, size = nodeSizes[kind], item?: SourceItem) {
  const id = canvasId()
  if (await edit({ type: 'add_node', node: { id, kind, position, size, text: '',
    color: kind === 'frame' ? 'blue' : 'yellow', reference: item?.reference || null } })) {
    selection.value = { type: 'node', id }
    if (kind === 'card') locate(id)
    else { paragraphId.value = ''; editorId.value = id }
  }
}

function attach(nodes: CanvasNode[]) {
  return nodes.filter(node => node.automatic && !savedIds.value.has(node.id)).map(nodeInput)
}

function updateNode(id: string, patch: NodePatch) {
  const node = nodesById.value.get(id)
  if (!node) return Promise.resolve(false)
  const children = node.kind === 'frame' && patch.position ? frameMembers(node, nodes.value) : []
  return edit({ type: 'update_node', id, patch }, attach([node, ...children]))
}

function locate(id: string) {
  focusedKind.value = null
  selection.value = { type: 'node', id }
  stage.value?.focusNodes([id])
}

function addParagraph(item: SourceItem) {
  const key = referenceKey(item.reference)
  const existing = nodes.value.find(node => node.reference && referenceKey(node.reference) === key)
  const document = nodesById.value.get(paragraphId.value)
  paragraphId.value = ''
  if (existing) { locate(existing.id); return }
  const position = document ? paragraphPosition(document, nodes.value) : stage.value?.insertionPoint('card')
  if (position) void create('card', position, nodeSizes.card, item)
}

function openNode(id: string) {
  const node = nodesById.value.get(id)
  if (!node) return
  selectedRelation.value = null
  if (node.kind !== 'card') {
    paragraphId.value = ''
    editorId.value = id
  } else {
    const target = assetOperation(props.workspaceId, node)
    if (target) void router.push(target)
  }
}

function editRelation(link: CanvasRelation) {
  if (!graph.value?.access.can_link_requirements || saving.value) return
  editorId.value = ''
  paragraphId.value = ''
  selectedRelation.value = { requirement_id: link.requirement_id, task_id: link.task_id }
}

function taskLinksPath(requirementId: string) {
  return `/workspaces/${encodeURIComponent(props.workspaceId)}/workspace-assets/requirements/${encodeURIComponent(requirementId)}/tasks`
}

async function saveRelation(type?: RequirementTaskRelation) {
  const link = relation.value
  if (!link || !graph.value?.access.can_link_requirements) return
  const path = `${taskLinksPath(link.requirement_id)}/${encodeURIComponent(link.task_id)}`
  const ok = await submit(() => type ? api.patch(path, { relation_type: type }) : api.delete(path))
  if (ok) {
    selectedRelation.value = null
    ElMessage.success(t(type ? 'workspace_assets.requirements.task_links.relation_updated' : 'workspace_assets.requirements.task_links.removed'))
  }
}

async function saveText(patch: NodePatch) {
  if (editorId.value && await updateNode(editorId.value, patch)) editorId.value = ''
}

async function removeSelected() {
  const item = selection.value
  if (!item || (item.type === 'node' && nodesById.value.get(item.id)?.automatic)) return
  if (await edit({ type: item.type === 'node' ? 'remove_node' : 'remove_edge', id: item.id })) selection.value = null
}

async function connect(source: string, target: string, mode: CanvasConnection) {
  const from = nodesById.value.get(source), to = nodesById.value.get(target)
  if (!from || !to) return
  const refs = [from.reference, to.reference]
  const requirement = refs.find(ref => ref?.kind === 'requirement')
  const task = refs.find(ref => ref?.kind === 'task')
  if (mode === 'arrow' || (mode === 'auto' && !(requirement && task))) {
    await edit({ type: 'add_edge', edge: { id: canvasId(), source, target } }, attach([from, to]))
    return
  }
  if (!requirement || !task) { ElMessage.info(t('workspace_canvas.relation_pair')); return }
  if (!graph.value?.access.can_link_requirements) { ElMessage.info(t('workspace_canvas.relation_permission')); return }
  const path = taskLinksPath(requirement.id)
  const linked = await submit(async () => {
    try {
      await api.post(path, { task_id: task.id, relation_type: 'RELATES_TO' })
    } catch (error) {
      const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
      if (response?.status !== 409 || response.data?.detail !== 'Requirement is already linked to this Task.') throw error
    }
  })
  if (linked) ElMessage.success(t('workspace_canvas.relation_saved'))
}

defineExpose({ refresh: () => refresh(true) })
</script>

<template>
  <section class="asset-graph glass-panel" data-testid="workspace-asset-graph">
    <header class="graph-toolbar">
      <div class="graph-title"><span><Workflow :size="21" /></span><h1>{{ t('workspace_canvas.title') }}</h1></div>
      <div v-if="graph" class="graph-actions">
        <span class="graph-sync" :class="{ interrupted: syncError, saving }" :title="syncError || undefined" role="status">
          <i aria-hidden="true" />{{ syncLabel }}
        </span>
        <CanvasAssetSearch :nodes="nodes" @locate="locate" />
        <CanvasAssetCommands :can-create-requirement="graph.access.can_link_requirements"
          :can-create-task="context.canCreateTask.value" :can-create-document="canUpload"
          :has-case-access="access.includes('case')"
          @command="command" />
      </div>
    </header>

    <nav v-if="graph && groups.length" class="graph-categories" :aria-label="t('workspace_canvas.actions.focus_assets')">
      <button type="button" :aria-pressed="focusedKind === null" @click="focusKind(null)">
        <LayoutGrid :size="15" />{{ t('workspace_canvas.actions.all') }}
      </button>
      <button v-for="kind in groups" :key="kind" type="button" :aria-pressed="focusedKind === kind" @click="focusKind(kind)">
        <component :is="sourceIcons[kind]" :size="15" />{{ t(`workspace_canvas.kind.${kind}`) }}
      </button>
    </nav>

    <div v-if="saveError && graph" class="graph-error" role="alert">
      <span>{{ saveError }}</span>
      <button v-if="canRetry" type="button" :disabled="saving" @click="retry"><RefreshCw :size="15" />{{ t('workspace_canvas.retry') }}</button>
      <button type="button" :aria-label="t('common.close')" @click="saveError = ''"><X :size="17" /></button>
    </div>

    <div v-if="graph" class="graph-layout">
      <CanvasStage ref="stage" :workspace-id="workspaceId" :data="graph" :selection="selection" :busy="saving"
        @select="value => selection = value" @create="create" @update="updateNode" @connect="connect"
        @open="openNode" @remove="removeSelected" @edit-relation="editRelation"
        @paragraphs="id => { editorId = ''; selectedRelation = null; paragraphId = id }">
        <CanvasTextEditor v-if="editor" :key="editor.id" :node="editor" :saving="saving" @save="saveText" @close="editorId = ''" />
        <CanvasParagraphPicker v-if="paragraphSource" :key="paragraphId" :workspace-id="workspaceId" :reference="paragraphSource.reference"
          :title="paragraphSource.title" :disabled="saving" @add="addParagraph" @close="paragraphId = ''" />
        <CanvasRelationEditor v-if="relation && relatedRequirement && relatedTask"
          :key="`${relation.requirement_id}:${relation.task_id}`" :link="relation"
          :requirement="relatedRequirement.title" :task="relatedTask.title" :saving="saving"
          :pending-acceptance="relatedRequirement.status === 'PENDING_ACCEPTANCE'"
          @update="saveRelation" @unlink="saveRelation()" @close="selectedRelation = null" />
      </CanvasStage>
      <slot name="workspace" />
    </div>
    <div v-else class="graph-state" :role="loading ? 'status' : 'alert'">
      <span>{{ loading ? t('common.loading') : syncError }}</span>
      <button v-if="!loading" class="btn-secondary" type="button" @click="refresh(true)">{{ t('workspace_canvas.retry') }}</button>
    </div>
    <CanvasAssetCreation v-if="graph" ref="assetCreation" :workspace-id="workspaceId" :tasks="tasks" @changed="refresh(true)" />
  </section>
</template>

<style scoped>
.asset-graph {
  --canvas-ink: #0f172a;
  --canvas-muted: #64748b;
  --canvas-paper: #f8fafc;
  --canvas-dot: #cddde8;
  --canvas-chrome: #fff;
  --canvas-line: #e2e8f0;
  --canvas-hover: #f0f9ff;
  --canvas-accent: #0369a1;
  --canvas-edge: #64748b;
  --canvas-relation: #0284c7;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  gap: 10px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: linear-gradient(149deg, #f4faff, #fff 33%);
}
.graph-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 9px; flex: 0 0 auto; padding: 1px 4px; }
.graph-title { display: flex; align-items: center; gap: 9px; }
.graph-title span { display: grid; place-items: center; padding: 8px; color: #0369a1; border-radius: 10px; background: #e0f2fe; }
.graph-title h1 { margin: 0; color: #1e3a8a; font-size: 19px; font-weight: 750; }
.graph-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.graph-categories { display: flex; gap: 4px; overflow: auto; padding: 0 4px 1px; }
.graph-categories button { display: inline-flex; align-items: center; gap: 5px; padding: 5px 9px; border-radius: 7px; border: 1px solid transparent; background: transparent; color: #475569; font: inherit; font-size: 12px; white-space: nowrap; cursor: pointer; }
.graph-categories button:hover, .graph-categories button[aria-pressed='true'] { background: #e0f2fe; color: #0369a1; border-color: #bae6fd; }
.graph-sync { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--canvas-muted); white-space: nowrap; }
.graph-sync i { width: 6px; height: 6px; border-radius: 50%; background: #319466; }
.graph-sync.interrupted i { background: #bc721f; }
.graph-sync.saving i { background: var(--canvas-accent); }
.graph-layout { position: relative; display: flex; flex: 1; min-height: 0; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 12px; }
.graph-state { flex: 1; display: flex; align-items: center; justify-content: center; gap: 10px; color: #64748b; font-size: 13px; }
.graph-error { display: flex; align-items: center; gap: 8px; padding: 5px 9px; border: 1px solid #f7d9df; border-radius: 7px; background: #fff1f3; color: #8f3143; font-size: 12px; }
.graph-error span { flex: 1; }
.graph-error button { display: inline-flex; align-items: center; gap: 5px; border: 0; padding: 4px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
@media (max-width: 850px) { .asset-graph { padding: 12px; } .graph-sync { display: none; } }
</style>
