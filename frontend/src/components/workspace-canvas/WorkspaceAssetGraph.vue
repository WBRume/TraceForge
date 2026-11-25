<script setup lang="ts">
import { computed, onMounted, shallowRef, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { LayoutGrid, RefreshCw, Workflow, X } from '@/components/icons'
import { requirementDocumentsUrl } from '@/components/workspace-assets/requirements/requirementDocuments'
import { useWorkspaceContext } from '@/composables/chat/tasklist/useWorkspaceContext'
import { canvasOperationTarget } from '@/router/workspaceAssetPresentation'
import { useProvisioningStore } from '@/stores/provisioning'
import type { RequirementTaskRelation } from '@/types/workspaceAssets'
import api from '@/utils/api'
import CanvasAssetCreation from './CanvasAssetCreation.vue'
import CanvasAssetSearch from './CanvasAssetSearch.vue'
import CanvasContextMenu from './CanvasContextMenu.vue'
import CanvasLinkDialog from './CanvasLinkDialog.vue'
import CanvasParagraphPicker from './CanvasParagraphPicker.vue'
import CanvasRelationEditor from './CanvasRelationEditor.vue'
import CanvasRelationProperties from './CanvasRelationProperties.vue'
import CanvasStage from './CanvasStage.vue'
import CanvasTextEditor from './CanvasTextEditor.vue'
import { layoutWorkspaceAssets, paragraphPosition } from './assetLayout'
import { menuIcons, type CanvasContextRequest, type CanvasMenuAction, type CanvasMenuItem } from './contextMenu'
import { frameMembers } from './geometry'
import { assetOperation, canvasId, isDocument, nodeInput, nodeSizes, referenceKey, sourceIcons, sourceKinds,
  type CanvasCommand, type CanvasConnection, type CanvasDocumentOwner, type CanvasNode, type CanvasSelection,
  type NodePatch, type Point, type SourceItem, type SourceKind, type SourceReference } from './model'
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
const selectedRelationId = shallowRef('')
const contextRequest = shallowRef<CanvasContextRequest | null>(null)
type LinkAction = 'link_task' | 'link_requirement' | 'share_document'
const linkRequest = shallowRef<{ id: string; action: LinkAction } | null>(null)
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
const canManage = computed(() => Boolean(graph.value?.access.can_link_requirements))
const groups = computed(() => sourceKinds.filter(kind => access.value.includes(kind) && kind !== 'plan_document' && kind !== 'requirement_document'))
const relation = computed(() => graph.value?.relations.find(row => row.id === selectedRelationId.value))
const sourceDetails = computed(() => nodesById.value.get(relation.value?.sourceNodeId ?? '')?.details)
const targetDetails = computed(() => nodesById.value.get(relation.value?.targetNodeId ?? '')?.details)
const canEditRelation = computed(() => canManage.value && (relation.value?.relation_type === 'COVERS' || relation.value?.relation_type === 'RELATES_TO'))
const canDetachDocument = computed(() => canManage.value && relation.value?.relation_type === 'DOCUMENT_REQUIREMENT' && Boolean(relation.value.link_id))
const parentRequirements = computed(() => new Set(graph.value?.relations.filter(row => row.relation_type === 'SUB_REQUIREMENT')
  .map(row => row.target.id)))
const childRequirements = computed(() => new Set(graph.value?.relations.filter(row => row.relation_type === 'SUB_REQUIREMENT')
  .map(row => row.source.id)))
const documentOwners = computed(() => snapshot.value?.assets.flatMap<CanvasDocumentOwner>(({ reference, details }) => {
  if (reference.kind === 'requirement' && canManage.value) return [{ kind: 'requirement', id: reference.id, title: details.title }]
  if (reference.kind === 'task' && context.workspacePermissions.value?.upload_task_spec) {
    return [{ kind: 'task', id: reference.id, title: details.title, taskType: details.task_type }]
  }
  return []
}) ?? [])
const paragraphSource = computed(() => {
  const node = nodesById.value.get(paragraphId.value)
  return node?.details && node.reference && isDocument(node.reference) && !node.reference.block
    ? { title: node.details.title, reference: node.reference } : null
})
const syncLabel = computed(() => t(saving.value ? 'workspace_canvas.saving' : syncError.value
  ? 'workspace_canvas.sync_paused' : readingPlans.value ? 'workspace_canvas.plan_loading' : 'workspace_canvas.synced'))
const linkSubject = computed(() => nodesById.value.get(linkRequest.value?.id ?? ''))
const linkItems = computed(() => {
  const action = linkRequest.value?.action
  const subject = linkSubject.value
  if (!subject) return []
  const linked = new Set<string>()
  for (const row of graph.value?.relations ?? []) {
    if (action === 'link_task' && row.source.kind === 'task' && row.targetNodeId === subject.id) linked.add(row.source.id)
    if (action !== 'link_task' && row.sourceNodeId === subject.id && row.target.kind === 'requirement') linked.add(row.target.id)
  }
  return snapshot.value?.assets.filter(({ reference }) => {
    if (linked.has(reference.id)) return false
    if (action === 'link_task') return reference.kind === 'task'
    return reference.kind === 'requirement' && (action === 'share_document' || !parentRequirements.value.has(reference.id))
  }) ?? []
})

watch(graph, next => {
  const current = selection.value
  if (current && !next?.[current.type === 'node' ? 'nodes' : 'edges'].some(item => item.id === current.id)) selection.value = null
  if (editorId.value && !editor.value) editorId.value = ''
  if (paragraphId.value && !paragraphSource.value) paragraphId.value = ''
  if (selectedRelationId.value && !relation.value) selectedRelationId.value = ''
})

function focusKind(kind: SourceKind | null) {
  focusedKind.value = kind
  if (!kind) { stage.value?.fit(); return }
  const items = nodes.value.filter(node => node.reference?.kind === kind
    || (kind === 'document' && node.reference && isDocument(node.reference)))
  if (!items.length) { ElMessage.info(t('workspace_canvas.no_results')); return }
  stage.value?.focusNodes(items.map(node => node.id))
}

function command(action: CanvasCommand, owner?: CanvasDocumentOwner) {
  selectedRelationId.value = ''
  assetCreation.value?.open(action, owner)
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
  selectedRelationId.value = ''
  if (node.kind !== 'card') {
    paragraphId.value = ''
    editorId.value = id
  } else {
    const target = assetOperation(props.workspaceId, node)
    if (target) void router.push(target)
  }
}

function openRelation(id: string) {
  editorId.value = ''
  paragraphId.value = ''
  selectedRelationId.value = id
}

function taskLinksPath(requirementId: string) {
  return `/workspaces/${encodeURIComponent(props.workspaceId)}/workspace-assets/requirements/${encodeURIComponent(requirementId)}/tasks`
}

async function saveRelation(type?: RequirementTaskRelation) {
  const link = relation.value
  if (!link || !canEditRelation.value) return
  const path = `${taskLinksPath(link.target.id)}/${encodeURIComponent(link.source.id)}`
  const ok = await submit(() => type ? api.patch(path, { relation_type: type }) : api.delete(path))
  if (ok) {
    selectedRelationId.value = ''
    ElMessage.success(t(type ? 'workspace_assets.requirements.task_links.relation_updated' : 'workspace_assets.requirements.task_links.removed'))
  }
}

async function detachDocument() {
  const link = relation.value
  if (!link?.link_id || !canDetachDocument.value) return
  const path = `${requirementDocumentsUrl(props.workspaceId, link.target.id)}/${encodeURIComponent(link.link_id)}`
  if (await submit(() => api.delete(path))) {
    selectedRelationId.value = ''
    ElMessage.success(t('workspace_assets.requirements.task_links.removed'))
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

async function linkTask(requirementId: string, taskId: string, type: RequirementTaskRelation) {
  const path = taskLinksPath(requirementId)
  let existing = false
  const linked = await submit(async () => {
    try {
      await api.post(path, { task_id: taskId, relation_type: type })
    } catch (error) {
      const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
      if (response?.status !== 409 || response.data?.detail !== 'Requirement is already linked to this Task.') throw error
      existing = true
    }
  })
  if (linked) {
    if (existing) ElMessage.info(t('workspace_canvas.relation_exists'))
    else ElMessage.success(t('workspace_canvas.relation_saved'))
  }
  return linked
}

async function shareDocument(requirementId: string, assetId: string) {
  const path = `${requirementDocumentsUrl(props.workspaceId, requirementId)}/task-assets/${encodeURIComponent(assetId)}`
  const linked = await submit(() => api.put(path))
  if (linked) ElMessage.success(t('workspace_canvas.relation_saved'))
  return linked
}

function isTaskDocument(reference: SourceReference | null) {
  return reference?.kind === 'document' && !reference.block && !reference.version_id
}

async function connect(source: string, target: string, mode: CanvasConnection) {
  const from = nodesById.value.get(source), to = nodesById.value.get(target)
  if (!from || !to) return
  if (mode === 'arrow' || (mode === 'auto' && (!from.reference || !to.reference))) {
    await edit({ type: 'add_edge', edge: { id: canvasId(), source, target } }, attach([from, to]))
    return
  }
  const refs = [from.reference, to.reference]
  const requirement = refs.find(ref => ref?.kind === 'requirement')
  const task = refs.find(ref => ref?.kind === 'task')
  const document = refs.find(isTaskDocument)
  if (!requirement || (!task && !document)) { ElMessage.info(t('workspace_canvas.relation_pair')); return }
  if (!canManage.value) { ElMessage.info(t('workspace_canvas.relation_permission')); return }
  if (document) await shareDocument(requirement.id, document.id)
  else if (task) await linkTask(requirement.id, task.id, 'RELATES_TO')
}

const contextItems = computed(() => {
  const target = contextRequest.value?.target
  const items: CanvasMenuItem[] = []
  function add(key: CanvasMenuAction, allowed = true, options?: Pick<CanvasMenuItem, 'divider' | 'danger' | 'disabled'>) {
    if (allowed) items.push({ key, label: t(`workspace_canvas.menu.${key}`), icon: menuIcons[key], ...options })
  }
  const write = { disabled: saving.value }
  const remove = { ...write, divider: true, danger: true }
  if (target?.type === 'surface') {
    add('new_requirement', canManage.value, write)
    add('new_task', context.canCreateTask.value, write)
    add('new_case', context.canCreateTask.value && access.value.includes('case'), write)
    add('upload', documentOwners.value.length > 0, write)
    add('playbooks', access.value.includes('playbook'))
    add('new_note', true, { ...write, divider: items.length > 0 })
    add('new_frame', true, write)
    add('fit', true, { divider: true })
  } else if (target?.type === 'relation') {
    add('properties')
    add('related')
  } else if (target?.type === 'edge') {
    add('related')
    add('delete', true, remove)
  } else if (target?.type === 'node') {
    const node = nodesById.value.get(target.id)
    if (!node) return items
    const ref = node.reference
    add('open')
    add('related', neighborIds(node.id).length > 1)
    add('upload', documentOwners.value.some(owner => owner.kind === ref?.kind && owner.id === ref.id), write)
    if (ref?.kind === 'requirement') {
      const leaf = !parentRequirements.value.has(ref.id)
      add('edit_requirement', canManage.value, write)
      add('child_requirement', canManage.value && !childRequirements.value.has(ref.id), write)
      add('create_linked_task', leaf && context.canCreateTask.value, write)
      add('link_task', leaf && canManage.value && access.value.includes('task'), write)
    } else if (ref?.kind === 'task') {
      add('task_session')
      add('task_documents', access.value.includes('document'))
      add('link_requirement', canManage.value, write)
    } else if (ref && isDocument(ref)) {
      add('share_document', canManage.value && isTaskDocument(ref), write)
      add('paragraphs', !ref.block, write)
    } else if (ref?.kind === 'case') {
      add('promote_case', context.canCreateTask.value && node.details?.status === 'APPROVED', write)
    }
    add('delete', !node.automatic, remove)
  }
  return items
})

function neighborIds(id: string) {
  const ids = new Set([id])
  for (const { sourceNodeId, targetNodeId } of graph.value?.relations ?? []) {
    if (sourceNodeId === id) ids.add(targetNodeId)
    if (targetNodeId === id) ids.add(sourceNodeId)
  }
  for (const { source, target } of graph.value?.edges ?? []) {
    if (source === id) ids.add(target)
    if (target === id) ids.add(source)
  }
  return [...ids]
}

function showContext(request: CanvasContextRequest) {
  const target = request.target
  selection.value = target.type === 'node' || target.type === 'edge' ? { type: target.type, id: target.id } : null
  contextRequest.value = request
}

function closeContext(returnFocus = false) {
  const request = contextRequest.value
  contextRequest.value = null
  if (returnFocus) request?.restoreFocus.focus({ preventScroll: true })
}

function focusContext(request: CanvasContextRequest) {
  const target = request.target
  if (target.type === 'node') stage.value?.focusNodes(neighborIds(target.id))
  else if (target.type === 'relation') {
    const link = graph.value?.relations.find(item => item.id === target.id)
    if (link) stage.value?.focusNodes([link.sourceNodeId, link.targetNodeId])
  } else if (target.type === 'edge') {
    const edge = graph.value?.edges.find(item => item.id === target.id)
    if (edge) stage.value?.focusNodes([edge.source, edge.target])
  }
}

function chooseContext(action: CanvasMenuAction) {
  const request = contextRequest.value
  if (!request) return
  const { target, position } = request
  const node = target.type === 'node' ? nodesById.value.get(target.id) : undefined
  const ref = node?.reference
  const params = { wsId: props.workspaceId }
  closeContext()
  switch (action) {
    case 'new_requirement': command('requirement'); break
    case 'new_task': command('task'); break
    case 'new_case': command('case'); break
    case 'playbooks': command('playbooks'); break
    case 'upload': command('document', documentOwners.value.find(owner => owner.kind === ref?.kind && owner.id === ref.id)); break
    case 'new_note': void create('note', position); break
    case 'new_frame': void create('frame', position); break
    case 'fit': stage.value?.fit(); break
    case 'open': if (node) openNode(node.id); break
    case 'related': focusContext(request); break
    case 'properties': if (target.type === 'relation') openRelation(target.id); break
    case 'delete': void removeSelected(); break
    case 'edit_requirement': case 'child_requirement':
      if (ref) void router.push(canvasOperationTarget(action === 'edit_requirement' ? 'workspaceAssetsRequirementEdit' : 'workspaceAssetsRequirementChild',
        { ...params, requirementId: ref.id }))
      break
    case 'create_linked_task': if (ref) void assetCreation.value?.createLinkedTask(ref.id); break
    case 'link_task': case 'link_requirement': case 'share_document':
      if (node) linkRequest.value = { id: node.id, action }
      break
    case 'task_session': case 'task_documents':
      if (ref) void router.push(canvasOperationTarget(action === 'task_session' ? 'taskChat' : 'taskSpec', { ...params, taskId: ref.id }))
      break
    case 'paragraphs':
      if (node) { editorId.value = ''; selectedRelationId.value = ''; paragraphId.value = node.id }
      break
    case 'promote_case': if (ref) void router.push(canvasOperationTarget('playbooks', params, { case: ref.id })); break
  }
}

async function saveLink(target: string, type: RequirementTaskRelation) {
  const action = linkRequest.value?.action
  const id = linkSubject.value?.reference?.id
  if (!action || !id) return
  const linked = action === 'share_document' ? await shareDocument(target, id)
    : action === 'link_task' ? await linkTask(id, target, type) : await linkTask(target, id, type)
  if (linked) linkRequest.value = null
}

defineExpose({ refresh: () => refresh(true) })
</script>

<template>
  <section class="asset-graph glass-panel" data-testid="workspace-asset-graph">
    <header class="graph-toolbar">
      <div class="graph-title"><span><Workflow :size="21" /></span><h1>{{ t('workspace_canvas.title') }}</h1></div>
      <span v-if="graph" class="graph-sync" :class="{ interrupted: syncError, saving }" :title="syncError || undefined" role="status">
        <i aria-hidden="true" />{{ syncLabel }}
      </span>
    </header>

    <nav v-if="graph && groups.length" class="graph-categories" :aria-label="t('workspace_canvas.actions.focus_assets')">
      <button type="button" :aria-pressed="focusedKind === null" @click="focusKind(null)">
        <LayoutGrid :size="15" />{{ t('workspace_canvas.actions.all') }}
      </button>
      <button v-for="kind in groups" :key="kind" type="button" :aria-pressed="focusedKind === kind" @click="focusKind(kind)">
        <component :is="sourceIcons[kind]" :size="15" />{{ t(`workspace_canvas.kind.${kind}`) }}
      </button>
      <CanvasAssetSearch class="category-search" :nodes="nodes" @locate="locate" />
    </nav>

    <div v-if="saveError && graph" class="graph-error" role="alert">
      <span>{{ saveError }}</span>
      <button v-if="canRetry" type="button" :disabled="saving" @click="retry"><RefreshCw :size="15" />{{ t('workspace_canvas.retry') }}</button>
      <button type="button" :aria-label="t('common.close')" @click="saveError = ''"><X :size="17" /></button>
    </div>

    <div v-if="graph" class="graph-layout">
      <CanvasStage ref="stage" :workspace-id="workspaceId" :data="graph" :selection="selection" :busy="saving"
        @select="value => selection = value" @create="create" @update="updateNode" @connect="connect"
        @open="openNode" @remove="removeSelected" @open-relation="openRelation" @context="showContext">
        <CanvasTextEditor v-if="editor" :key="editor.id" :node="editor" :saving="saving" @save="saveText" @close="editorId = ''" />
        <CanvasParagraphPicker v-if="paragraphSource" :key="paragraphId" :workspace-id="workspaceId" :reference="paragraphSource.reference"
          :title="paragraphSource.title" :disabled="saving" @add="addParagraph" @close="paragraphId = ''" />
        <CanvasRelationEditor v-if="relation && sourceDetails && targetDetails && canEditRelation"
          :key="relation.id" :link="relation" :requirement="targetDetails.title" :task="sourceDetails.title" :saving="saving"
          :pending-acceptance="targetDetails.status === 'PENDING_ACCEPTANCE'"
          @update="saveRelation" @unlink="saveRelation()" @close="selectedRelationId = ''" />
        <CanvasRelationProperties v-else-if="relation && sourceDetails && targetDetails" :key="relation.id"
          :link="relation" :source-title="sourceDetails.title" :target-title="targetDetails.title"
          :can-detach="canDetachDocument" :saving="saving" @detach="detachDocument" @close="selectedRelationId = ''" />
        <CanvasContextMenu v-if="contextRequest && contextItems.length" :request="contextRequest" :items="contextItems"
          :label="t('workspace_canvas.menu.label')" @choose="chooseContext" @close="closeContext" />
      </CanvasStage>
      <slot name="workspace" />
    </div>
    <div v-else class="graph-state" :role="loading ? 'status' : 'alert'">
      <span>{{ loading ? t('common.loading') : syncError }}</span>
      <button v-if="!loading" class="btn-secondary" type="button" @click="refresh(true)">{{ t('workspace_canvas.retry') }}</button>
    </div>
    <CanvasAssetCreation v-if="graph" ref="assetCreation" :workspace-id="workspaceId" :document-owners="documentOwners" @changed="refresh(true)" />
    <CanvasLinkDialog v-if="linkRequest && linkSubject?.details" :title="t(`workspace_canvas.menu.${linkRequest.action}`)"
      :label="linkSubject.details.title" :items="linkItems" :document="linkRequest.action === 'share_document'" :saving="saving"
      @close="linkRequest = null" @save="saveLink" />
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
.graph-categories { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; padding: 0 4px 1px; }
.category-search { margin-inline-start: 6px; }
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
