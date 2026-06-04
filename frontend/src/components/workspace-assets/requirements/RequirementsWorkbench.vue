<script setup lang="ts">
import { computed, reactive, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import RequirementEditDrawer from './RequirementEditDrawer.vue'
import RequirementImportDialog from './RequirementImportDialog.vue'
import RequirementTableWorkbench from './RequirementTableWorkbench.vue'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import type {
  RequirementImportBatch,
  RequirementImportConfirmPayload,
  RequirementListQuery,
  RequirementMutationPayload,
  RequirementPreviewJob,
  RequirementSplitPayload,
  RequirementSummary,
  WorkspaceAssetsRequirements,
} from '@/types/workspaceAssets'

const props = defineProps<{
  workspaceId: string
  requirements: readonly RequirementSummary[]
  loading?: boolean
}>()

const emit = defineEmits<{
  refresh: []
}>()

const route = useRoute()
const router = useRouter()
const {
  loading: actionLoading,
  error,
  loadRequirements,
  createRequirement,
  updateRequirement,
  createRequirementImportPreview,
  directImportRequirement,
  confirmRequirementImport,
  createRequirementSplitPreview,
  confirmRequirementSplit,
} = useWorkspaceAssets()

function routeString(key: string): string | undefined {
  const value = route.query[key]
  return typeof value === 'string' && value.trim() ? value : undefined
}

function routeNumber(key: string, fallback: number): number {
  const value = Number(routeString(key))
  return Number.isFinite(value) && value > 0 ? value : fallback
}

const tableQuery = reactive<RequirementListQuery>({
  q: routeString('q'),
  status: routeString('status'),
  priority: routeString('priority'),
  source_kind: routeString('source_kind'),
  parent_id: routeString('parentId'),
  scope: 'tree',
  sort_by: (routeString('sort_by') as RequirementListQuery['sort_by']) || 'updated_at',
  sort_order: (routeString('sort_order') as RequirementListQuery['sort_order']) || 'desc',
  page: routeNumber('page', 1),
  page_size: routeNumber('page_size', 20),
})
const requirementsResponse = shallowRef<WorkspaceAssetsRequirements | null>(null)
const editorOpen = shallowRef(false)
const editingRequirement = shallowRef<RequirementSummary | null>(null)
const childParent = shallowRef<RequirementSummary | null>(null)
const createOpen = shallowRef(false)
const createBatch = shallowRef<RequirementImportBatch | null>(null)
const createPreviewJob = shallowRef<RequirementPreviewJob | null>(null)
const createPreviewRunId = shallowRef(0)
const splitBatch = shallowRef<RequirementImportBatch | null>(null)
const splitPreviewJob = shallowRef<RequirementPreviewJob | null>(null)
const splitPreviewRunId = shallowRef(0)
const splitRequirement = shallowRef<RequirementSummary | null>(null)

const fallbackResponse = computed<WorkspaceAssetsRequirements>(() => ({
  workspace_id: props.workspaceId,
  items: [...props.requirements],
  total: props.requirements.length,
  page: 1,
  page_size: 20,
  scope: 'tree',
  state: {
    empty: props.requirements.length === 0,
    message: props.requirements.length ? null : 'Requirement source is not connected or has no records.',
  },
  connection_status: [],
}))
const activeResponse = computed(() => requirementsResponse.value || fallbackResponse.value)
const requirementItems = computed(() => activeResponse.value.items)
const requestedRequirementId = computed(() => {
  const value = route.query.requirementId
  return typeof value === 'string' ? value : null
})

function currentQuery(): RequirementListQuery {
  return { ...tableQuery }
}

async function reloadRequirements(query: RequirementListQuery = currentQuery()) {
  const result = await loadRequirements(props.workspaceId, query)
  if (result) requirementsResponse.value = result
  return result
}

async function openRequirement(requirement: RequirementSummary) {
  await openRequirementById(requirement.id)
}

async function openRequirementById(requirementId: string) {
  await router.push({
    name: 'workspaceAssetsRequirementDetail',
    params: {
      wsId: props.workspaceId,
      requirementId,
    },
  })
}

async function handleQueryChange(query: RequirementListQuery) {
  Object.assign(tableQuery, {
    q: undefined,
    status: undefined,
    priority: undefined,
    source_kind: undefined,
    parent_id: undefined,
    sort_by: 'updated_at',
    sort_order: 'desc',
    page: 1,
    page_size: 20,
  }, query)
  await reloadRequirements()
  const nextQuery = { ...route.query }
  for (const key of ['q', 'status', 'priority', 'source_kind', 'sort_by', 'sort_order', 'page', 'page_size', 'parentId']) {
    delete nextQuery[key]
  }
  if (tableQuery.q) nextQuery.q = String(tableQuery.q)
  if (tableQuery.status) nextQuery.status = String(tableQuery.status)
  if (tableQuery.priority) nextQuery.priority = String(tableQuery.priority)
  if (tableQuery.source_kind) nextQuery.source_kind = String(tableQuery.source_kind)
  if (tableQuery.parent_id) nextQuery.parentId = String(tableQuery.parent_id)
  if (tableQuery.sort_by && tableQuery.sort_by !== 'updated_at') nextQuery.sort_by = tableQuery.sort_by
  if (tableQuery.sort_order && tableQuery.sort_order !== 'desc') nextQuery.sort_order = tableQuery.sort_order
  if (tableQuery.page && tableQuery.page > 1) nextQuery.page = String(tableQuery.page)
  if (tableQuery.page_size && tableQuery.page_size !== 20) nextQuery.page_size = String(tableQuery.page_size)
  await router.replace({ query: nextQuery })
}

function openCreate() {
  childParent.value = null
  createBatch.value = null
  createPreviewJob.value = null
  createOpen.value = true
}

function openCreateChild(parent: RequirementSummary) {
  childParent.value = parent
  editingRequirement.value = null
  editorOpen.value = true
}

function openEdit(requirement: RequirementSummary) {
  childParent.value = null
  editingRequirement.value = requirement
  editorOpen.value = true
}

async function refreshAfterMutation(nextRequirementId?: string | null) {
  await reloadRequirements()
  emit('refresh')
  if (nextRequirementId) {
    await openRequirementById(nextRequirementId)
  }
}

async function submitEditor(payload: RequirementMutationPayload) {
  const result = editingRequirement.value
    ? await updateRequirement(props.workspaceId, editingRequirement.value.id, payload)
    : await createRequirement(props.workspaceId, {
      ...payload,
      parent_requirement_id: childParent.value?.id || payload.parent_requirement_id || null,
    })
  if (result) {
    editorOpen.value = false
    editingRequirement.value = null
    childParent.value = null
    await refreshAfterMutation(result.requirement.id)
  }
}

async function previewImport(payload: Parameters<typeof createRequirementImportPreview>[1]) {
  createPreviewRunId.value += 1
  const runId = createPreviewRunId.value
  createBatch.value = null
  createPreviewJob.value = null
  const batch = await createRequirementImportPreview(
    props.workspaceId,
    payload,
    (job) => {
      if (runId === createPreviewRunId.value) createPreviewJob.value = job
    },
  )
  if (batch && runId === createPreviewRunId.value) createBatch.value = batch
}

async function confirmImport(payload: RequirementImportConfirmPayload) {
  if (!createBatch.value) return
  const batch = await confirmRequirementImport(props.workspaceId, createBatch.value.id, payload)
  if (!batch) return
  createBatch.value = batch
  createOpen.value = false
  createPreviewJob.value = null
  await reloadRequirements()
  emit('refresh')
  const root = requirementItems.value.find((item) => item.import_batch_id === batch.id && !item.parent_requirement_id)
  const directCreated = batch.items.find((item) => item.requirement_id)
  if (root) {
    await openRequirement(root)
  } else if (directCreated?.requirement_id) {
    await openRequirementById(directCreated.requirement_id)
  }
}

async function submitCreatedRequirement(payload: RequirementMutationPayload) {
  const result = await createRequirement(props.workspaceId, payload)
  if (result) {
    createOpen.value = false
    await refreshAfterMutation(result.requirement.id)
  }
}

async function directImport(payload: Parameters<typeof directImportRequirement>[1]) {
  const result = await directImportRequirement(props.workspaceId, payload)
  if (result) {
    createOpen.value = false
    await refreshAfterMutation(result.requirement.id)
  }
}

async function openSplit(requirement: RequirementSummary) {
  splitPreviewRunId.value += 1
  const runId = splitPreviewRunId.value
  splitRequirement.value = requirement
  splitBatch.value = null
  splitPreviewJob.value = null
  const batch = await createRequirementSplitPreview(
    props.workspaceId,
    requirement.id,
    null,
    (job) => {
      if (runId === splitPreviewRunId.value) splitPreviewJob.value = job
    },
  )
  if (batch && runId === splitPreviewRunId.value) splitBatch.value = batch
}

async function confirmSplit(payload: RequirementImportConfirmPayload) {
  if (!splitBatch.value || !splitRequirement.value) return
  const splitPayload: RequirementSplitPayload = {
    batch_id: splitBatch.value.id,
    items: payload.items,
    change_reason: payload.change_reason,
  }
  const batch = await confirmRequirementSplit(props.workspaceId, splitRequirement.value.id, splitPayload)
  if (batch) {
    const parentId = splitRequirement.value.id
    splitBatch.value = null
    splitPreviewJob.value = null
    splitRequirement.value = null
    await refreshAfterMutation(parentId)
  }
}

function ignorePreview() {
  createBatch.value = null
}

function clearCreatePreviewJob() {
  createPreviewJob.value = null
}

function closeCreateDialog() {
  createPreviewRunId.value += 1
  createOpen.value = false
  createPreviewJob.value = null
}

function closeSplitDialog() {
  splitPreviewRunId.value += 1
  splitBatch.value = null
  splitPreviewJob.value = null
}

watch(
  () => props.workspaceId,
  async (workspaceId) => {
    if (!workspaceId) return
    await reloadRequirements()
    if (requestedRequirementId.value) {
      await openRequirementById(requestedRequirementId.value)
    }
  },
  { immediate: true },
)

watch(
  requestedRequirementId,
  async (requirementId) => {
    if (!requirementId) return
    const nextQuery = { ...route.query }
    delete nextQuery.requirementId
    await router.replace({
      name: 'workspaceAssetsRequirementDetail',
      params: {
        wsId: props.workspaceId,
        requirementId,
      },
      query: nextQuery,
    })
  },
)
</script>

<template>
  <section class="requirements-workbench">
    <p v-if="error" class="error-note">{{ error }}</p>

    <RequirementTableWorkbench
      :items="requirementItems"
      :total="activeResponse.total"
      :page="activeResponse.page"
      :page-size="activeResponse.page_size"
      :loading="props.loading || actionLoading"
      @query-change="handleQueryChange"
      @open="openRequirement"
      @create="openCreate"
      @create-child="openCreateChild"
      @edit="openEdit"
      @split="openSplit"
    />

    <RequirementEditDrawer
      :open="editorOpen"
      :requirement="editingRequirement"
      :loading="actionLoading"
      @close="editorOpen = false"
      @submit="submitEditor"
    />

    <RequirementImportDialog
      :open="createOpen"
      mode="create"
      :batch="createBatch"
      :preview-job="createPreviewJob"
      :loading="actionLoading"
      @close="closeCreateDialog"
      @manual="submitCreatedRequirement"
      @direct="directImport"
      @preview="previewImport"
      @confirm="confirmImport"
      @discard-preview="ignorePreview"
      @clear-preview-job="clearCreatePreviewJob"
    />

    <RequirementImportDialog
      :open="Boolean(splitBatch || splitPreviewJob)"
      mode="split"
      :batch="splitBatch"
      :preview-job="splitPreviewJob"
      :loading="actionLoading"
      @close="closeSplitDialog"
      @preview="ignorePreview"
      @confirm="confirmSplit"
      @clear-preview-job="closeSplitDialog"
    />
  </section>
</template>

<style scoped>
.requirements-workbench {
  display: flex;
  flex-direction: column;
  gap: 18px;
  animation: slide-up 0.4s ease-out;
}

@keyframes slide-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.error-note {
  margin: 0;
  padding: 1rem 1.5rem;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 12px;
  background: #fef2f2;
  color: #dc2626;
  font-size: 0.875rem;
  font-weight: 600;
}
</style>
