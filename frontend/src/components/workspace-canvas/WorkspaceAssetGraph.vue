<script setup lang="ts">
import { computed, nextTick, onMounted, shallowRef, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { LayoutGrid, RefreshCw, Workflow, X } from '@/components/icons'
import { requirementDocumentsUrl } from '@/components/workspace-assets/requirements/requirementDocuments'
import { useWorkspaceContext } from '@/composables/chat/tasklist/useWorkspaceContext'
import { canvasOperationTarget, WORKSPACE_ASSET_CANVAS } from '@/router/workspaceAssetPresentation'
import { useAuthStore } from '@/stores/auth'
import { useProvisioningStore } from '@/stores/provisioning'
import type { RequirementTaskRelation } from '@/types/workspaceAssets'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import CanvasAssetCreation from './CanvasAssetCreation.vue'
import CanvasAssetSearch from './CanvasAssetSearch.vue'
import CanvasContextMenu from './CanvasContextMenu.vue'
import CanvasLinkDialog from './CanvasLinkDialog.vue'
import CanvasParagraphPicker from './CanvasParagraphPicker.vue'
import CanvasQuarterPicker from './CanvasQuarterPicker.vue'
import CanvasRootControls from './CanvasRootControls.vue'
import CanvasRelationEditor from './CanvasRelationEditor.vue'
import CanvasRelationProperties from './CanvasRelationProperties.vue'
import CanvasStage from './CanvasStage.vue'
import CanvasTextEditor from './CanvasTextEditor.vue'
import { buildCanvasCatalog } from './assetDomains'
import { layoutWorkspace, paragraphPosition, translatePoint } from './assetLayout'
import { menuIcons, type CanvasContextRequest, type CanvasMenuAction, type CanvasMenuItem } from './contextMenu'
import { frameMembers } from './geometry'
import { assetOperation, canvasId, isDocument, nodeInput, nodeSizes, referenceKey,
  type CanvasAsset, type CanvasAssetWindow, type CanvasCommand, type CanvasConnection, type CanvasDocumentOwner,
  type CanvasNode, type CanvasRelation, type CanvasRootFilters, type CanvasRootKind, type CanvasSelection, type CanvasSnapshot,
  type NodePatch, type Point, type SourceItem, type SourceReference } from './model'
import { useCanvasAssetWindows } from './useCanvasAssetWindows'
import { useCanvasRoots } from './useCanvasRoots'
import { useWorkspaceCanvas } from './useWorkspaceCanvas'

const props = defineProps<{ workspaceId: string }>()
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const requestedQuarter = computed(() => typeof route.query.quarter === 'string' && /^\d{4}-Q[1-4]$/.test(route.query.quarter)
  ? route.query.quarter : undefined)
const stage = useTemplateRef<InstanceType<typeof CanvasStage>>('stage')
const assetCreation = useTemplateRef<InstanceType<typeof CanvasAssetCreation>>('assetCreation')
const selection = shallowRef<CanvasSelection | null>(null)
const editorId = shallowRef('')
const paragraphId = shallowRef('')
const selectedRelationId = shallowRef('')
const contextRequest = shallowRef<CanvasContextRequest | null>(null)
type LinkAction = 'link_task' | 'link_requirement' | 'share_document'
const linkRequest = shallowRef<{ id: string; action: LinkAction } | null>(null)
const context = useWorkspaceContext({ getWorkspaceId: () => props.workspaceId })
const jobs = useProvisioningStore()
const { snapshot, planFiles, readingPlans, setPlanTasks, loading, saving, syncError, saveError, canRetry, refresh, edit, retry, submit } =
  useWorkspaceCanvas(props.workspaceId, () => requestedQuarter.value)
const quarter = computed(() => snapshot.value?.quarter)
const roots = useCanvasRoots(props.workspaceId)
const { page: rootPage, filters: rootFilters, history: rootHistory, loading: loadingRoots } = roots
const primary = computed(() => rootPage.value ?? snapshot.value)
const rootCursor = computed(() => rootPage.value ? rootPage.value.next_cursor : snapshot.value?.root_cursor)
const rootKinds = computed(() => snapshot.value?.access.source_kinds.filter((kind): kind is CanvasRootKind =>
  kind !== 'plan_document') ?? [])
const { windows, located, treeParents, expanded, loadingKey, load, collapse, sync, search, clear: clearWindows } =
  useCanvasAssetWindows(props.workspaceId, () => quarter.value?.id, () => primary.value?.assets ?? [])
const loadingWindow = computed(() => Boolean(loadingKey.value))

onMounted(() => { void context.loadWorkspace().catch(() => {}) })
watch(() => jobs.taskListRefreshToken, () => { void refreshBoard() })
watch(snapshot, async (value, previous) => {
  if (!value || value.quarter?.id !== previous?.quarter?.id || value.root_tree !== previous?.root_tree) {
    clearWindows()
    roots.clear()
    selection.value = null
    contextRequest.value = null
    return
  }
  if (value.root_tree && value.quarter) await roots.sync(value.quarter.id)
  void sync()
})
const summaryOnly = computed(() => !windows.value.length)
function mergePages(base: CanvasSnapshot | null, pages: CanvasAssetWindow[]) {
  if (!base) return base
  const assets = new Map(base.assets.map(asset => [asset.node_id, asset]))
  const relations = new Map<string, CanvasRelation>()
  for (const page of [base, ...pages]) {
    for (const asset of page.assets) assets.set(asset.node_id, { ...assets.get(asset.node_id), ...asset,
      has_related: asset.has_related ?? assets.get(asset.node_id)?.has_related })
    for (const link of page.relations) {
      relations.set(JSON.stringify([referenceKey(link.source), referenceKey(link.target), link.relation_type]), link)
    }
  }
  return { ...base, assets: [...assets.values()], relations: [...relations.values()],
    treeParents: base.root_tree ? treeParents.value : undefined }
}
const scene = computed(() => {
  const base = snapshot.value
  if (!base) return null
  const page = rootPage.value
  const selected = page ? { ...base, assets: page.assets, relations: page.relations } : base
  const scoped = located.value ? { ...selected, assets: [...selected.assets, located.value] } : selected
  return mergePages(scoped, windows.value)
})
const catalog = computed(() => {
  const data = scene.value
  if (!data) return null
  const liveIds = new Set(data.assets.filter(asset => asset.reference.kind === 'task'
    && (!data.root_tree || expanded.value.has(referenceKey(asset.reference)))).map(asset => asset.reference.id))
  return buildCanvasCatalog(data, summaryOnly.value ? [] : planFiles.value.filter(file => liveIds.has(file.reference.id)))
})
const graph = computed(() => scene.value && catalog.value ? layoutWorkspace(scene.value, catalog.value, summaryOnly.value) : null)
const nodes = computed(() => graph.value?.nodes || [])
const nodesById = computed(() => new Map(nodes.value.map(node => [node.id, node])))
const savedIds = computed(() => new Set(snapshot.value?.nodes.map(node => node.id)))
const editor = computed(() => nodesById.value.get(editorId.value))
const access = computed(() => snapshot.value?.access.source_kinds ?? [])
const canManage = computed(() => Boolean(snapshot.value?.access.can_link_requirements))
const relation = computed(() => graph.value?.relations.find(row => row.id === selectedRelationId.value))
const sourceDetails = computed(() => nodesById.value.get(relation.value?.sourceNodeId ?? '')?.details)
const targetDetails = computed(() => nodesById.value.get(relation.value?.targetNodeId ?? '')?.details)
const canEditRelation = computed(() => canManage.value && (relation.value?.relation_type === 'COVERS' || relation.value?.relation_type === 'RELATES_TO'))
const canDetachDocument = computed(() => canManage.value && relation.value?.relation_type === 'DOCUMENT_REQUIREMENT' && Boolean(relation.value.link_id))
const parentRequirements = computed(() => new Set(scene.value?.relations.filter(row => row.relation_type === 'SUB_REQUIREMENT')
  .map(row => row.target.id)))
const childRequirements = computed(() => new Set(scene.value?.relations.filter(row => row.relation_type === 'SUB_REQUIREMENT')
  .map(row => row.source.id)))
const documentOwners = computed(() => scene.value?.assets.flatMap<CanvasDocumentOwner>(({ reference, details }) => {
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
function availableLinkItems(assets: CanvasAsset[]) {
  const action = linkRequest.value?.action
  const subject = linkSubject.value?.reference
  if (!subject) return []
  const linked = new Set<string>()
  for (const row of scene.value?.relations ?? []) {
    if (action === 'link_task' && row.source.kind === 'task' && row.target.kind === 'requirement' && row.target.id === subject.id) linked.add(row.source.id)
    if (action !== 'link_task' && row.source.kind === subject.kind && row.source.id === subject.id && row.target.kind === 'requirement') linked.add(row.target.id)
  }
  return assets.filter(({ reference }) => {
    if (linked.has(reference.id)) return false
    if (action === 'link_task') return reference.kind === 'task'
    return reference.kind === 'requirement' && (action === 'share_document' || !parentRequirements.value.has(reference.id))
  })
}
const linkItems = computed(() => availableLinkItems(scene.value?.assets ?? []))
const searchLinks = async (query: string, signal: AbortSignal) => availableLinkItems(await search(query, signal,
  linkRequest.value?.action === 'link_task' ? 'task' : 'requirement'))

watch(graph, next => {
  const current = selection.value
  if (current && !next?.[current.type === 'node' ? 'nodes' : 'edges'].some(item => item.id === current.id)) selection.value = null
  if (editorId.value && !editor.value) editorId.value = ''
  if (paragraphId.value && !paragraphSource.value) paragraphId.value = ''
  if (selectedRelationId.value && !relation.value) selectedRelationId.value = ''
})

function locateId(id: string) {
  const nodeId = graph.value?.assetNodeIds.get(id)
  if (!nodeId) return false
  focusNode(nodeId)
  return true
}

function showReadError(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  ElMessage.warning(detail === 'CANVAS_QUERY_BUSY' ? t('workspace_canvas.domains.query_busy')
    : formatApiError(error, t('workspace_canvas.load_failed'), t))
}

async function loadWindow(reference: SourceReference, options?: Parameters<typeof load>[1]) {
  try {
    const data = await load(reference, options)
    if (data === 'limit') {
      ElMessage.info(t('workspace_canvas.tree.expansion_limit'))
      return null
    }
    return data
  } catch (error) {
    showReadError(error)
    return null
  }
}

async function locateAsset(asset: CanvasAsset) {
  if (asset.quarter && quarter.value && asset.quarter.id !== quarter.value.id) {
    await selectQuarter(asset.quarter.id)
    await nextTick()
  }
  if (locateId(asset.node_id)) return
  if (graph.value && await loadWindow(asset.reference, { locate: true })) {
    await nextTick()
    if (locateId(asset.node_id)) return
  }
  const target = assetOperation(props.workspaceId, asset)
  if (target) void router.push(withQuarter(target, asset.quarter?.id))
}

async function fitOverview() {
  clearWindows()
  roots.clear()
  selection.value = null
  await nextTick()
  stage.value?.fit()
}

async function expandNeighborhood(nodeId: string, keepPosition = false, options: NonNullable<Parameters<typeof load>[1]> = {}) {
  const node = nodesById.value.get(nodeId)
  const reference = node?.reference
  if (!node || node.historicalQuarter || !reference || reference.kind === 'plan_document' || ('block' in reference && reference.block)) return
  const branch = expanded.value.get(referenceKey(reference))
  if (branch && !options.cursor && !options.previous && !options.locate && !options.reveal) {
    if (!keepPosition) stage.value?.focusNodes(neighborIds(nodeId).slice(0, 4))
    return
  }
  const alreadyVisible = new Set(catalog.value?.byId.keys())
  const page = await loadWindow(reference, options)
  if (!page) return
  await nextTick()
  const asset = catalog.value?.byReference.get(referenceKey(reference))
  const id = asset && graph.value?.assetNodeIds.get(asset.node_id)
  if (!id) return
  if (expanded.value.get(referenceKey(reference))?.empty) ElMessage.info(t('workspace_canvas.tree.no_neighbors'))
  if (keepPosition) {
    stage.value?.keepInView(node.position, id)
    const revealKey = options.reveal && referenceKey(options.reveal)
    const first = revealKey ? page.assets.find(asset => referenceKey(asset.reference) === revealKey)
      : page.assets.find(asset => !alreadyVisible.has(asset.node_id))
    const child = first && graph.value?.assetNodeIds.get(first.node_id)
    if (child) stage.value?.revealChild(id, child)
  }
  else focusNode(id)
}

async function toggleBranch(id: string) {
  const node = nodesById.value.get(id)
  if (!node?.expandable || !node.reference) return
  if (expanded.value.has(referenceKey(node.reference))) {
    const reference = node.reference
    collapse(reference)
    await nextTick()
    const asset = catalog.value?.byReference.get(referenceKey(reference))
    const moved = asset && graph.value?.assetNodeIds.get(asset.node_id)
    if (moved) stage.value?.keepInView(node.position, moved)
  } else await expandNeighborhood(id, true)
}

function moreNeighbors(id: string) {
  const ref = nodesById.value.get(id)?.reference
  const cursor = ref && expanded.value.get(referenceKey(ref))?.cursor
  if (cursor) void expandNeighborhood(id, true, { cursor })
}

function withQuarter(target: ReturnType<typeof canvasOperationTarget>, id = quarter.value?.id) {
  return { ...target, query: { ...target.query, quarter: id } }
}

async function selectQuarter(id: string) {
  await router.push({ name: WORKSPACE_ASSET_CANVAS, params: { wsId: props.workspaceId }, query: { quarter: id } })
  await refresh()
}

async function calendarSaved(id: string) {
  clearWindows()
  roots.clear()
  await selectQuarter(id)
  await nextTick()
  stage.value?.fit()
}

async function browseRoots(direction: 'next' | 'previous' | CanvasRootFilters) {
  const period = quarter.value
  if (!period) return
  try {
    const cursor = rootCursor.value
    const loaded = direction === 'previous' ? await roots.previous(period.id) : direction === 'next'
      ? Boolean(cursor && await roots.next(period.id, cursor)) : await roots.filter(period.id, direction)
    if (!loaded || quarter.value?.id !== period.id) return
    clearWindows()
    selection.value = null
    contextRequest.value = null
    await nextTick()
    stage.value?.fit()
  } catch (error) {
    showReadError(error)
  }
}

function annotationScope(position: Point) {
  return graph.value?.regions.find(region => region.type !== 'section'
    && position.x >= region.position.x && position.x < region.position.x + region.size.width
    && position.y >= region.position.y && position.y < region.position.y + region.size.height)?.id
    ?? (quarter.value ? `quarter-${quarter.value.id}` : null)
}

function storedPosition(position: Point, scopeId?: string | null) {
  const offset = scopeId ? graph.value?.scopeOffsets.get(scopeId) : undefined
  return offset ? translatePoint(position, offset, -1) : position
}

function command(action: CanvasCommand, owner?: CanvasDocumentOwner) {
  selectedRelationId.value = ''
  assetCreation.value?.open(action, owner)
}

async function create(kind: CanvasNode['kind'], position: Point, size = nodeSizes[kind], item?: SourceItem,
  scopeId = annotationScope(position)) {
  const id = canvasId()
  if (await edit({ type: 'add_node', node: { id, kind, position: storedPosition(position, scopeId), size, text: '',
    color: kind === 'frame' ? 'blue' : 'yellow', reference: item?.reference || null, scope_id: scopeId } })) {
    selection.value = { type: 'node', id }
    if (kind === 'card') focusNode(id)
    else { paragraphId.value = ''; editorId.value = id }
  }
}

function attach(nodes: CanvasNode[]) {
  return nodes.filter(node => node.automatic && node.reference && !node.historicalQuarter && !savedIds.value.has(node.id))
    .map(node => nodeInput({ ...node, position: storedPosition(node.position, node.scope_id) }))
}

function updateNode(id: string, patch: NodePatch) {
  const node = nodesById.value.get(id)
  if (!node || node.historicalQuarter) return Promise.resolve(false)
  const children = node.kind === 'frame' && patch.position ? frameMembers(node, nodes.value) : []
  const storedPatch = patch.position ? { ...patch, position: storedPosition(patch.position, node.scope_id) } : patch
  return edit({ type: 'update_node', id, patch: storedPatch }, attach([node, ...children]))
}

function focusNode(id: string) {
  selection.value = { type: 'node', id }
  stage.value?.focusNodes([id])
}

function addParagraph(item: SourceItem) {
  const key = referenceKey(item.reference)
  const existing = nodes.value.find(node => node.reference && referenceKey(node.reference) === key)
  const document = nodesById.value.get(paragraphId.value)
  paragraphId.value = ''
  if (existing) { focusNode(existing.id); return }
  const position = document ? paragraphPosition(document, nodes.value) : stage.value?.insertionPoint('card')
  if (position) void create('card', position, nodeSizes.card, item, document?.scope_id ?? annotationScope(position))
}

function openNode(id: string) {
  const node = nodesById.value.get(id)
  if (!node) return
  selectedRelationId.value = ''
  if (node.historicalQuarter) {
    void openHistorical(node)
  } else if (node.kind !== 'card') {
    paragraphId.value = ''
    editorId.value = id
  } else {
    const target = assetOperation(props.workspaceId, node)
    if (target) void router.push(withQuarter(target))
  }
}

async function openHistorical(node: CanvasNode) {
  const target = assetOperation(props.workspaceId, node)
  if (!target || !node.reference || !node.historicalQuarter) return
  const period = node.historicalQuarter.id
  await router.push(withQuarter(target, period))
  if (!await refresh() || quarter.value?.id !== period) return
  await nextTick()
  const locate = () => {
    const source = catalog.value?.byReference.get(referenceKey(node.reference!))
    return source ? locateId(source.node_id) : false
  }
  if (!locate() && await loadWindow(node.reference, { locate: true })) { await nextTick(); locate() }
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

async function revealRelation(requirementId: string, neighbor: SourceReference, period?: string) {
  if (quarter.value?.id !== period) return
  const requirement: SourceReference = { kind: 'requirement', id: requirementId }
  const assetFor = (ref: SourceReference) => catalog.value?.byReference.get(referenceKey(ref))
  const requirementAsset = assetFor(requirement)
  const anchor = requirementAsset?.quarter && requirementAsset.quarter.id !== period ? neighbor : requirement
  const related = anchor === neighbor ? requirement : neighbor
  const focus = assetFor(anchor)
  const nodeId = focus && graph.value?.assetNodeIds.get(focus.node_id)
  if (nodeId) {
    await expandNeighborhood(nodeId, true, { reveal: related })
    return
  }
  let page = await loadWindow(anchor, { locate: true, reveal: related })
  if (anchor === requirement && page?.assets[0]?.quarter?.id !== period) {
    page = await loadWindow(neighbor, { locate: true, reveal: requirement })
  }
  if (!page) return
  await nextTick()
  const endpoints = page.assets.filter(asset => [referenceKey(anchor), referenceKey(related)].includes(referenceKey(asset.reference)))
  stage.value?.focusNodes(endpoints.flatMap(asset => {
    const id = graph.value?.assetNodeIds.get(asset.node_id)
    return id ? [id] : []
  }))
}

async function linkTask(requirementId: string, taskId: string, type: RequirementTaskRelation) {
  const path = taskLinksPath(requirementId)
  const period = quarter.value?.id
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
    await revealRelation(requirementId, { kind: 'task', id: taskId }, period)
  }
  return linked
}

async function shareDocument(requirementId: string, assetId: string) {
  const path = `${requirementDocumentsUrl(props.workspaceId, requirementId)}/task-assets/${encodeURIComponent(assetId)}`
  const period = quarter.value?.id
  const linked = await submit(() => api.put(path))
  if (linked) {
    ElMessage.success(t('workspace_canvas.relation_saved'))
    await revealRelation(requirementId, { kind: 'document', id: assetId }, period)
  }
  return linked
}

function isTaskDocument(reference: SourceReference | null) {
  return reference?.kind === 'document' && !reference.block && !reference.version_id
}

async function connect(source: string, target: string, mode: CanvasConnection) {
  const from = nodesById.value.get(source), to = nodesById.value.get(target)
  if (!from || !to) return
  if (mode === 'arrow' && (from.historicalQuarter || to.historicalQuarter)) return
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
    add('fit', Boolean(graph.value), { divider: true })
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
    if (node.historicalQuarter) return items
    add('related', Boolean(ref && !('block' in ref && ref.block) && ref.kind !== 'plan_document') || neighborIds(node.id).length > 1,
      { disabled: loadingWindow.value })
    const assetId = ref && catalog.value?.byReference.get(referenceKey(ref))?.node_id
    add('start_branch', Boolean(snapshot.value?.root_tree && node.expandable && assetId && node.domainId !== assetId),
      { disabled: loadingWindow.value })
    add('upload', documentOwners.value.some(owner => owner.kind === ref?.kind && owner.id === ref.id), write)
    if (ref?.kind === 'requirement') {
      const leaf = !node.details?.has_children && !parentRequirements.value.has(ref.id)
      add('edit_requirement', canManage.value, write)
      add('child_requirement', canManage.value && !node.details?.parent_requirement_id && !childRequirements.value.has(ref.id), write)
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

async function focusContext(request: CanvasContextRequest) {
  const target = request.target
  if (target.type === 'node') {
    const reference = nodesById.value.get(target.id)?.reference
    if (reference && reference.kind !== 'plan_document' && !('block' in reference && reference.block)) {
      await expandNeighborhood(target.id)
      return
    }
    stage.value?.focusNodes(neighborIds(target.id))
  } else if (target.type === 'relation') {
    const link = graph.value?.relations.find(item => item.id === target.id)
    if (link) stage.value?.focusNodes([link.sourceNodeId, link.targetNodeId])
  } else if (target.type === 'edge') {
    const edge = graph.value?.edges.find(item => item.id === target.id)
    if (edge) stage.value?.focusNodes([edge.source, edge.target])
  }
}

function showParagraphs(node: CanvasNode) {
  editorId.value = ''
  selectedRelationId.value = ''
  paragraphId.value = node.id
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
    case 'fit': void fitOverview(); break
    case 'open': if (node) openNode(node.id); break
    case 'related': void focusContext(request); break
    case 'start_branch': if (node) void expandNeighborhood(node.id, false, { locate: true }); break
    case 'properties': if (target.type === 'relation') openRelation(target.id); break
    case 'delete': void removeSelected(); break
    case 'edit_requirement': case 'child_requirement':
      if (ref) void router.push(withQuarter(canvasOperationTarget(action === 'edit_requirement' ? 'workspaceAssetsRequirementEdit' : 'workspaceAssetsRequirementChild',
        { ...params, requirementId: ref.id })))
      break
    case 'create_linked_task': if (ref) void assetCreation.value?.createLinkedTask(ref.id); break
    case 'link_task': case 'link_requirement': case 'share_document':
      if (node) linkRequest.value = { id: node.id, action }
      break
    case 'task_session': case 'task_documents':
      if (ref) void router.push(withQuarter(canvasOperationTarget(action === 'task_session' ? 'taskChat' : 'taskSpec', { ...params, taskId: ref.id })))
      break
    case 'paragraphs':
      if (node) showParagraphs(node)
      break
    case 'promote_case': if (ref) void router.push(withQuarter(canvasOperationTarget('playbooks', params, { case: ref.id }))); break
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

const refreshBoard = () => refresh(true)

defineExpose({ refresh: refreshBoard })
</script>

<template>
  <section class="asset-graph glass-panel" data-testid="workspace-asset-graph">
    <header class="graph-toolbar">
      <div class="graph-title"><span><Workflow :size="21" /></span><h1>{{ t('workspace_canvas.title') }}</h1></div>
      <span v-if="catalog" class="graph-sync" :class="{ interrupted: syncError, saving }" :title="syncError || undefined" role="status">
        <i aria-hidden="true" />{{ syncLabel }}
      </span>
    </header>

    <nav class="graph-navigation" :aria-label="t('workspace_canvas.title')">
      <CanvasQuarterPicker v-if="quarter" :workspace-id="workspaceId" :quarter="quarter" :busy="loading || saving"
        @select="selectQuarter" @calendar-saved="calendarSaved" />
      <button v-if="graph" type="button" @click="fitOverview">
        <LayoutGrid :size="15" />{{ t('workspace_canvas.quarter.overview') }}
      </button>
      <CanvasAssetSearch class="category-search" :assets="catalog?.assets ?? []" :remote="search" @locate="locateAsset" />
      <span v-if="loading || loadingWindow || loadingRoots" class="graph-summary" role="status">{{ t('common.loading') }}</span>
      <span v-if="snapshot?.annotations_limited" class="graph-summary" role="status">{{ t('workspace_canvas.domains.annotation_limit') }}</span>
    </nav>
    <CanvasRootControls v-if="snapshot?.root_tree && quarter" :key="quarter.id" :quarter="quarter" :kinds="rootKinds"
      :filters="rootFilters" :next="!!rootCursor" :previous="!!rootHistory.length" :busy="loadingRoots || loading"
      :empty="!primary?.assets.length" :user-id="auth.user?.id" @filter="browseRoots" @next="browseRoots('next')" @previous="browseRoots('previous')" />

    <div v-if="saveError && catalog" class="graph-error" role="alert">
      <span>{{ saveError }}</span>
      <button v-if="canRetry" type="button" :disabled="saving" @click="retry"><RefreshCw :size="15" />{{ t('workspace_canvas.retry') }}</button>
      <button type="button" :aria-label="t('common.close')" @click="saveError = ''"><X :size="17" /></button>
    </div>

    <div class="graph-layout">
      <CanvasStage v-if="graph" ref="stage" :data="graph" :selection="selection" :busy="saving || loading" :summary="summaryOnly"
        :expanded="expanded" :expanding="loadingKey"
        @select="value => selection = value" @create="create" @update="updateNode" @connect="connect"
        @open="openNode" @remove="removeSelected" @open-relation="openRelation" @context="showContext" @visible-tasks="setPlanTasks"
        @expand="id => !loading && !loadingWindow && expandNeighborhood(id, true)"
        @toggle-branch="toggleBranch" @more-branch="moreNeighbors" @previous-branch="id => expandNeighborhood(id, true, { previous: true })">
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
      </CanvasStage>
      <div v-else class="graph-state" :role="loading ? 'status' : 'alert'">
        <span>{{ loading ? t('common.loading') : syncError }}</span>
        <button v-if="!loading" class="btn-secondary" type="button" @click="refresh(true)">{{ t('workspace_canvas.retry') }}</button>
      </div>
      <CanvasContextMenu v-if="contextRequest && contextItems.length" :request="contextRequest" :items="contextItems"
        :label="t('workspace_canvas.menu.label')" @choose="chooseContext" @close="closeContext" />
      <slot name="workspace" />
    </div>
    <CanvasAssetCreation v-if="catalog" ref="assetCreation" :workspace-id="workspaceId" :document-owners="documentOwners" @changed="refreshBoard" />
    <CanvasLinkDialog v-if="linkRequest && linkSubject?.details" :title="t(`workspace_canvas.menu.${linkRequest.action}`)"
      :label="linkSubject.details.title" :items="linkItems" :lookup="searchLinks"
      :document="linkRequest.action === 'share_document'" :saving="saving"
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
.graph-navigation { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; padding: 0 4px 1px; }
.category-search { margin-inline-start: 6px; }
.graph-navigation > button { display: inline-flex; align-items: center; gap: 5px; padding: 5px 9px; border-radius: 7px; border: 1px solid #cce1f2; background: #f1f8fe; color: #285978; font: inherit; font-size: 12px; white-space: nowrap; cursor: pointer; }
.graph-navigation > button:hover { background: #e0f2fe; color: #0369a1; border-color: #bae6fd; }
.graph-summary { color: #526781; margin-inline-start: 8px; font-size: 12px; font-variant-numeric: tabular-nums; }
.graph-navigation + .root-controls { padding: 0 4px 2px; }
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
