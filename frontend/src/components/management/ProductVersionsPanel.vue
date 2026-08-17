<!--
ProductVersionsPanel: a product evolves through versions (A1 -> A2 -> ...).
Each version card lists its own repository bindings and supports creating,
editing, deleting versions and binding/unbinding version-specific repositories.
New versions may inherit the product base repository pool, copy an existing
version, or start empty.
-->
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CalendarDays, Check, GitBranch, Pencil, Plus, Tag as TagIcon, Trash2, X } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import IconActionButton from '@/components/management/IconActionButton.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import RefNameInput from '@/components/management/RefNameInput.vue'
import RepoGroupPicker from '@/components/management/RepoGroupPicker.vue'
import {
  addBaselineExclusion,
  bindVersionRepo,
  createProductVersion,
  deleteProductVersion,
  getProduct,
  getRepoGroupTree,
  unbindVersionRepo,
  updateProductVersion,
  updateVersionRepoRef,
  updateVersionRepoRefsBatch,
} from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type {
  CustomProductVersionRef,
  EffectiveRepoBinding,
  ProductDetail,
  ProductRepoBinding,
  ProductVersion,
  ProductVersionDetail,
  ProductVersionStatus,
  RepoGroupTreeNode,
  RepoRefType,
} from '@/types/management'

const props = defineProps<{
  product: ProductDetail | null;
  canManage: boolean;
  focusVersionId?: string | null;
}>()

const emit = defineEmits<{
  (e: 'changed'): void;
}>()

const { t } = useI18n()
const router = useRouter()

const versions = computed<ProductVersionDetail[]>(() => props.product?.versions ?? [])

const allowedRepoTypes = computed(() =>
  props.product?.product_type === 'CUSTOM' ? ['CUSTOM'] : ['OOTB']
)

// 版本仓库采用下钻查看：默认只展示版本概要，点击后展开该版本的仓库绑定。
const expandedVersionId = ref<string | null>(null)

// 版本内仓库列表支持筛选与翻页。
const repoKeyword = ref('')
const repoPage = ref(1)
const repoPageSize = 10

const toggleVersionRepos = (version: ProductVersionDetail): void => {
  expandedVersionId.value = expandedVersionId.value === version.id ? null : version.id
  repoKeyword.value = ''
  repoPage.value = 1
}

const openProductVersion = (productId: string, versionId: string): void => {
  router.push({
    path: '/management/products/' + productId,
    query: { mode: 'view', version: versionId },
  })
}

const customVersionsModal = ref<{ title: string; items: CustomProductVersionRef[] } | null>(null)

const openCustomVersionsModal = (version: ProductVersionDetail): void => {
  customVersionsModal.value = {
    title: version.version_no,
    items: version.custom_versions ?? [],
  }
}

const closeCustomVersionsModal = (): void => {
  customVersionsModal.value = null
}

const jumpToCustomVersion = (item: CustomProductVersionRef): void => {
  customVersionsModal.value = null
  openProductVersion(item.product_id, item.id)
}

watch(
  () => props.focusVersionId,
  (id) => {
    if (id && versions.value.some((v) => v.id === id)) {
      expandedVersionId.value = id
      repoKeyword.value = ''
      repoPage.value = 1
    }
  },
  { immediate: true },
)

watch(
  versions,
  (list) => {
    const id = props.focusVersionId
    if (id && list.some((v) => v.id === id)) {
      expandedVersionId.value = id
      repoKeyword.value = ''
      repoPage.value = 1
    }
  },
  { immediate: true },
)

const filteredBindings = (version: ProductVersionDetail): EffectiveRepoBinding[] => {
  const kw = repoKeyword.value.trim().toLowerCase()
  const bindings = version.effective_repo_bindings ?? version.repo_bindings ?? []
  if (!kw) return bindings
  return bindings.filter((binding) =>
    String(binding.repository_name || '').toLowerCase().includes(kw)
    || String(binding.git_url || '').toLowerCase().includes(kw)
    || String(binding.ref_name || '').toLowerCase().includes(kw)
  )
}

const pagedBindings = (version: ProductVersionDetail): EffectiveRepoBinding[] => {
  const filtered = filteredBindings(version)
  const start = (repoPage.value - 1) * repoPageSize
  return filtered.slice(start, start + repoPageSize)
}

const repoTotalPages = (version: ProductVersionDetail): number =>
  Math.max(1, Math.ceil(filteredBindings(version).length / repoPageSize))

const goRepoPage = (version: ProductVersionDetail, delta: number): void => {
  const next = repoPage.value + delta
  if (next < 1 || next > repoTotalPages(version)) return
  repoPage.value = next
}

const versionStatusLabel = (status: ProductVersionStatus): string =>
  t('management.product.version_status_' + status.toLowerCase())

const versionStatusClass = (status: ProductVersionStatus): string => {
  if (status === 'ACTIVE') return 'blue'
  if (status === 'EOL') return 'red'
  return 'gray'
}

const formatDate = (value: string | null): string =>
  value ? value.slice(0, 10) : '-'

// ── Version form (create / edit) ──────────────────────────────────────────

const formVisible = ref(false)
const editingVersion = ref<ProductVersion | null>(null)
const savingVersion = ref(false)

type RepoInitMode = 'empty' | 'product_base' | 'from_version'

const versionForm = reactive<{
  version_no: string;
  status: ProductVersionStatus;
  release_date: string;
  description: string;
  repo_init_mode: RepoInitMode;
  from_version_id: string;
  baseline_product_version_id: string;
  inherit_ref_type: RepoRefType;
  inherit_ref_name: string;
}>({
  version_no: '',
  status: 'ACTIVE',
  release_date: '',
  description: '',
  repo_init_mode: 'empty',
  from_version_id: '',
  baseline_product_version_id: '',
  inherit_ref_type: 'BRANCH',
  inherit_ref_name: '',
})

const versionStatusOptions = computed(() => (
  (['PLANNED', 'ACTIVE', 'EOL'] as ProductVersionStatus[]).map((status) => ({
    label: versionStatusLabel(status),
    value: status,
  }))
))

const baselineVersions = ref<ProductVersion[]>([])
const baselineVersionOptions = computed(() =>
  baselineVersions.value.map((version) => ({ label: version.version_no, value: version.id }))
)

const loadBaselineVersions = async (): Promise<void> => {
  baselineVersions.value = []
  if (!props.product?.baseline_product_id) return
  try {
    const detail = await getProduct(props.product.baseline_product_id)
    baselineVersions.value = detail.versions ?? []
  } catch {
    baselineVersions.value = []
  }
}

const repoInitModeOptions = computed(() => [
  { label: t('management.product.repo_init_empty'), value: 'empty' as const },
  { label: t('management.product.repo_init_product_base'), value: 'product_base' as const },
  { label: t('management.product.repo_init_from_version'), value: 'from_version' as const },
])

// 复制已有版本时可选任意既有版本，支持多路演进。
const evolutionOptions = computed(() =>
  versions.value.map((version) => ({ label: version.version_no, value: version.id }))
)

const refTypeOptions = computed(() => [
  { label: t('management.product.ref_branch'), value: 'BRANCH' as RepoRefType },
  { label: t('management.product.ref_tag'), value: 'TAG' as RepoRefType },
])

const openCreateVersion = () => {
  editingVersion.value = null
  versionForm.version_no = ''
  versionForm.status = 'ACTIVE'
  versionForm.release_date = ''
  versionForm.description = ''
  versionForm.repo_init_mode = (props.product?.base_repos.length ?? 0) > 0 ? 'product_base' : 'empty'
  versionForm.from_version_id = ''
  versionForm.baseline_product_version_id = ''
  versionForm.inherit_ref_type = 'BRANCH'
  versionForm.inherit_ref_name = ''
  if (props.product?.product_type === 'CUSTOM') {
    void loadBaselineVersions()
  } else {
    baselineVersions.value = []
  }
  formVisible.value = true
}

const openEditVersion = (version: ProductVersion) => {
  editingVersion.value = version
  versionForm.version_no = version.version_no
  versionForm.status = version.status
  versionForm.release_date = version.release_date?.slice(0, 10) ?? ''
  versionForm.description = version.description ?? ''
  versionForm.repo_init_mode = 'empty'
  versionForm.from_version_id = ''
  versionForm.baseline_product_version_id = version.baseline_product_version_id ?? ''
  versionForm.inherit_ref_type = 'BRANCH'
  versionForm.inherit_ref_name = ''
  if (props.product?.product_type === 'CUSTOM') {
    void loadBaselineVersions()
  } else {
    baselineVersions.value = []
  }
  formVisible.value = true
}

const saveVersion = async () => {
  if (!props.product) return
  if (!versionForm.version_no.trim()) {
    ElMessage.warning(t('management.common.required'))
    return
  }
  if (!editingVersion.value && versionForm.repo_init_mode === 'from_version' && !versionForm.from_version_id) {
    ElMessage.warning(t('management.product.repo_init_from_version_required'))
    return
  }
  if (props.product?.product_type === 'CUSTOM' && !versionForm.baseline_product_version_id) {
    ElMessage.warning(t('management.product.baseline_version_required'))
    return
  }
  savingVersion.value = true
  try {
    if (editingVersion.value) {
      await updateProductVersion(props.product.id, editingVersion.value.id, {
        version_no: versionForm.version_no.trim(),
        status: versionForm.status,
        release_date: versionForm.release_date || null,
        description: versionForm.description.trim() || null,
      })
    } else {
      await createProductVersion(props.product.id, {
        version_no: versionForm.version_no.trim(),
        status: versionForm.status,
        release_date: versionForm.release_date || null,
        description: versionForm.description.trim() || null,
        from_version_id: versionForm.repo_init_mode === 'from_version' ? versionForm.from_version_id : null,
        baseline_product_version_id: versionForm.baseline_product_version_id || null,
        inherit_product_repos: versionForm.repo_init_mode === 'product_base',
        inherit_ref_type: versionForm.repo_init_mode === 'product_base' ? versionForm.inherit_ref_type : null,
        inherit_ref_name: versionForm.repo_init_mode === 'product_base' && versionForm.inherit_ref_name.trim()
          ? versionForm.inherit_ref_name.trim()
          : null,
      })
    }
    formVisible.value = false
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    savingVersion.value = false
  }
}

const deletingVersion = ref<ProductVersion | null>(null)
const deletingVersionLoading = ref(false)

const confirmDeleteVersion = async () => {
  if (!props.product || !deletingVersion.value) return
  deletingVersionLoading.value = true
  try {
    await deleteProductVersion(props.product.id, deletingVersion.value.id)
    deletingVersion.value = null
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deletingVersionLoading.value = false
  }
}

// ── Repository binding per version ────────────────────────────────────────

type RefValue = { ref_type: RepoRefType; ref_name: string }

const pickerVisible = ref(false)
const pickerTargetVersionId = ref<string | null>(null)
const selectedRepoIds = ref<string[]>([])
const pendingRefs = ref<Record<string, RefValue>>({})
const repoNameMap = ref<Record<string, string>>({})
const savingBinding = ref(false)

const repoName = (repoId: string): string => repoNameMap.value[repoId] ?? repoId

const loadRepoNames = async () => {
  try {
    const res = await getRepoGroupTree()
    const map: Record<string, string> = {}
    for (const node of res.items ?? []) {
      collectNames(node, map)
    }
    repoNameMap.value = map
  } catch (err) {
    console.error(err)
  }
}

const collectNames = (node: RepoGroupTreeNode, map: Record<string, string>): void => {
  for (const repo of node.repositories) {
    map[repo.id] = repo.name
  }
  for (const child of node.children) {
    collectNames(child, map)
  }
}

const openPickerFor = (version: ProductVersionDetail) => {
  pickerTargetVersionId.value = version.id
  selectedRepoIds.value = []
  pendingRefs.value = {}
  pickerVisible.value = true
  void loadRepoNames()
}

const cancelPicker = () => {
  pickerVisible.value = false
  pickerTargetVersionId.value = null
  selectedRepoIds.value = []
  pendingRefs.value = {}
}

const confirmPicker = () => {
  pickerVisible.value = false
  if (selectedRepoIds.value.length === 0) {
    pickerTargetVersionId.value = null
  }
  // 保留 pickerTargetVersionId，使下方待绑定仓库的 ref 配置区域继续显示。
}

const cancelPendingBindings = () => {
  pickerTargetVersionId.value = null
  selectedRepoIds.value = []
  pendingRefs.value = {}
}

const defaultRef = (): RefValue => ({ ref_type: 'BRANCH', ref_name: '' })

const ensureRef = (repoId: string): RefValue => {
  if (!pendingRefs.value[repoId]) {
    pendingRefs.value[repoId] = defaultRef()
  }
  return pendingRefs.value[repoId]
}

const updatePendingRef = (repoId: string, value: RefValue) => {
  pendingRefs.value[repoId] = value
}

const saveBindings = async () => {
  if (!props.product || !pickerTargetVersionId.value) return
  const ids = selectedRepoIds.value
  if (ids.length === 0) return

  savingBinding.value = true
  try {
    for (const repoId of ids) {
      const ref = pendingRefs.value[repoId] ?? defaultRef()
      if (!ref.ref_name.trim()) {
        ElMessage.warning(t('management.common.required'))
        return
      }
      await bindVersionRepo(props.product.id, pickerTargetVersionId.value, {
        repository_id: repoId,
        ref_type: ref.ref_type,
        ref_name: ref.ref_name.trim(),
      })
    }
    pickerTargetVersionId.value = null
    selectedRepoIds.value = []
    pendingRefs.value = {}
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    savingBinding.value = false
  }
}

// ── Edit existing binding ref (branch/tag) ───────────────────────────────

const editingBinding = ref<{
  versionId: string;
  bindingId: string;
  repositoryId: string;
  ref: RefValue;
} | null>(null)
const savingRefBindingId = ref<string | null>(null)

const openEditBinding = (version: ProductVersionDetail, binding: ProductRepoBinding): void => {
  editingBinding.value = {
    versionId: version.id,
    bindingId: binding.id,
    repositoryId: binding.repository_id,
    ref: { ref_type: binding.ref_type, ref_name: binding.ref_name },
  }
}

const cancelEditBinding = (): void => {
  editingBinding.value = null
}

const updateEditingRef = (value: RefValue): void => {
  if (editingBinding.value) {
    editingBinding.value.ref = value
  }
}

const saveBindingRef = async (version: ProductVersionDetail): Promise<void> => {
  if (!props.product || !editingBinding.value) return
  const target = editingBinding.value
  if (!target.ref.ref_name.trim()) {
    ElMessage.warning(t('management.common.required'))
    return
  }
  savingRefBindingId.value = target.bindingId
  try {
    await updateVersionRepoRef(
      props.product.id,
      version.id,
      target.repositoryId,
      {
        ref_type: target.ref.ref_type,
        ref_name: target.ref.ref_name.trim(),
      },
    )
    editingBinding.value = null
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    savingRefBindingId.value = null
  }
}

// ── Batch update all binding refs ─────────────────────────────────────────

const batchRefVersionId = ref<string | null>(null)
const batchRef = reactive<RefValue>({ ref_type: 'BRANCH', ref_name: '' })
const batchScope = ref<'custom' | 'baseline'>('custom')
const batchSaving = ref(false)

const batchScopeOptions = computed(() => {
  const version = versions.value.find((v) => v.id === batchRefVersionId.value)
  const options: { label: string; value: 'custom' | 'baseline' }[] = [
    { label: t('management.product.batch_scope_custom'), value: 'custom' },
  ]
  if (version?.baseline_product_version_id) {
    options.push({ label: t('management.product.batch_scope_baseline'), value: 'baseline' })
  }
  return options
})

const openBatchRef = (version: ProductVersionDetail): void => {
  batchRefVersionId.value = version.id
  batchRef.ref_type = 'BRANCH'
  batchRef.ref_name = ''
  batchScope.value = 'custom'
}

const closeBatchRef = (): void => {
  if (batchSaving.value) return
  batchRefVersionId.value = null
}

const saveBatchRef = async (): Promise<void> => {
  if (!props.product || !batchRefVersionId.value) return
  if (!batchRef.ref_name.trim()) {
    ElMessage.warning(t('management.common.required'))
    return
  }
  batchSaving.value = true
  try {
    await updateVersionRepoRefsBatch(
      props.product.id,
      batchRefVersionId.value,
      {
        ref_type: batchRef.ref_type,
        ref_name: batchRef.ref_name.trim(),
        scope: batchScope.value,
      },
    )
    batchRefVersionId.value = null
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    batchSaving.value = false
  }
}

const excludingRepoId = ref<string | null>(null)

const excludeBaselineRepo = async (version: ProductVersionDetail, repositoryId: string): Promise<void> => {
  if (!props.product) return
  excludingRepoId.value = repositoryId
  try {
    await addBaselineExclusion(props.product.id, version.id, repositoryId)
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    excludingRepoId.value = null
  }
}

// ── Override a baseline repository ref ────────────────────────────────────

const overrideTarget = ref<{
  version: ProductVersionDetail;
  repositoryId: string;
  repositoryName: string;
} | null>(null)
const overrideRef = reactive<RefValue>({ ref_type: 'BRANCH', ref_name: '' })
const overrideSaving = ref(false)

const openOverride = (version: ProductVersionDetail, binding: EffectiveRepoBinding): void => {
  overrideTarget.value = {
    version,
    repositoryId: binding.repository_id,
    repositoryName: binding.repository_name || binding.repository_id,
  }
  overrideRef.ref_type = 'BRANCH'
  overrideRef.ref_name = binding.ref_name
}

const closeOverride = (): void => {
  if (overrideSaving.value) return
  overrideTarget.value = null
}

const updateOverrideRef = (value: RefValue): void => {
  overrideRef.ref_type = value.ref_type
  overrideRef.ref_name = value.ref_name
}

const saveOverride = async (): Promise<void> => {
  if (!props.product || !overrideTarget.value) return
  if (!overrideRef.ref_name.trim()) {
    ElMessage.warning(t('management.common.required'))
    return
  }
  overrideSaving.value = true
  try {
    await bindVersionRepo(
      props.product.id,
      overrideTarget.value.version.id,
      {
        repository_id: overrideTarget.value.repositoryId,
        ref_type: overrideRef.ref_type,
        ref_name: overrideRef.ref_name.trim(),
      },
    )
    overrideTarget.value = null
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    overrideSaving.value = false
  }
}

const unbindTarget = ref<{ version: ProductVersionDetail; repositoryId: string } | null>(null)
const unbinding = ref(false)

const confirmUnbind = async () => {
  if (!props.product || !unbindTarget.value) return
  unbinding.value = true
  try {
    await unbindVersionRepo(
      props.product.id,
      unbindTarget.value.version.id,
      unbindTarget.value.repositoryId,
    )
    unbindTarget.value = null
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    unbinding.value = false
  }
}

watch(
  () => selectedRepoIds.value,
  (ids) => {
    for (const id of ids) {
      ensureRef(id)
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="mgmt-card">
    <div class="mgmt-section-head">
      <h3>{{ $t('management.product.versions_title') }}</h3>
      <button v-if="canManage" class="btn-secondary" @click="openCreateVersion">
        <Plus class="w-4 h-4" /> {{ $t('management.product.add_version') }}
      </button>
    </div>

    <div v-if="versions.length === 0" class="mgmt-empty">
      {{ $t('management.product.no_versions') }}
    </div>

    <div v-else class="version-list">
      <div v-for="version in versions" :key="version.id" class="version-card">
        <div class="version-card-head">
          <span class="version-no">{{ version.version_no }}</span>
          <span class="mgmt-status-pill" :class="versionStatusClass(version.status)">
            {{ versionStatusLabel(version.status) }}
          </span>
          <span class="version-release">
            <CalendarDays class="w-4 h-4 version-release-icon" />
            {{ $t('management.product.release_date') }}：
            <span v-if="version.release_date" class="mgmt-status-pill green">
              {{ formatDate(version.release_date) }}
            </span>
            <span v-else class="mgmt-status-pill gray">-</span>
          </span>
          <button class="btn-ghost version-bind-btn" @click="toggleVersionRepos(version)">
            <GitBranch class="w-4 h-4" />
            {{ expandedVersionId === version.id
              ? $t('management.product.hide_repos')
              : $t('management.product.view_repos') }}
          </button>
          <span v-if="canManage" class="version-actions">
            <IconActionButton
              :icon="Pencil"
              :title="$t('management.product.edit_version')"
              @click="openEditVersion(version)"
            />
            <IconActionButton
              :icon="Trash2"
              :title="$t('common.delete')"
              tone="danger"
              @click="deletingVersion = version"
            />
          </span>
        </div>

        <p v-if="version.description" class="version-desc">{{ version.description }}</p>

        <div v-if="version.baseline_product_version_id" class="version-baseline-info">
          <span class="mgmt-hint">{{ $t('management.product.baseline_product') }}:
            <a class="mgmt-link" href="javascript:void(0)" @click="openProductVersion(version.baseline_product_id ?? '', version.baseline_product_version_id)">{{ version.baseline_product_name || '-' }}</a>
          </span>
          <span class="mgmt-hint">{{ $t('management.product.baseline_product_version') }}:
            <a class="mgmt-link" href="javascript:void(0)" @click="openProductVersion(version.baseline_product_id ?? '', version.baseline_product_version_id)">{{ version.baseline_version_no || '-' }}</a>
          </span>
        </div>

        <div v-if="version.custom_versions && version.custom_versions.length > 0" class="version-custom-inheritors">
          <span class="version-custom-inheritors-title">{{ $t('management.product.custom_versions_title') }}</span>
          <button class="btn-ghost version-bind-btn" @click="openCustomVersionsModal(version)">
            {{ $t('management.product.view_custom_versions', { count: version.custom_versions.length }) }}
          </button>
        </div>

        <div v-if="expandedVersionId === version.id" class="version-bindings">
          <div class="version-bindings-head">
            <span class="version-bindings-title">{{ $t('management.product.bindings_title') }}</span>
            <div v-if="version.repo_bindings.length > 0" class="version-bind-filter">
              <input
                v-model="repoKeyword"
                class="mgmt-input version-repo-search"
                type="text"
                :placeholder="$t('management.repository.search_placeholder')"
                @input="repoPage = 1"
              />
              <span class="text-muted">{{ $t('management.common.total_count', { count: filteredBindings(version).length }) }}</span>
            </div>
            <div v-if="canManage" class="version-bind-tools">
              <button
                v-if="version.repo_bindings.length > 0"
                class="btn-ghost version-bind-btn"
                @click="openBatchRef(version)"
              >
                <GitBranch class="w-4 h-4" /> {{ $t('management.product.batch_update_ref') }}
              </button>
              <button class="btn-ghost version-bind-btn" @click="openPickerFor(version)">
                <Plus class="w-4 h-4" /> {{ $t('management.product.add_binding') }}
              </button>
            </div>
          </div>

          <div v-if="version.repo_bindings.length === 0" class="mgmt-empty version-empty">
            {{ $t('management.product.no_bindings') }}
          </div>

          <div v-else-if="filteredBindings(version).length === 0" class="mgmt-empty version-empty">
            {{ $t('management.common.empty') }}
          </div>

          <table v-else class="mgmt-table">
            <thead>
              <tr>
                <th>{{ $t('management.product.binding_repo') }}</th>
                <th>{{ $t('management.common.type') }}</th>
                <th>{{ $t('management.product.ref_name') }}</th>
                <th v-if="canManage">{{ $t('management.common.actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="binding in pagedBindings(version)" :key="binding.id">
                <tr>
                  <td>
                    <div class="mgmt-repo-cell">
                      <div class="mgmt-repo-name-row">
                        <span class="mgmt-repo-name">{{ binding.repository_name }}</span>
                        <span v-if="binding.source" class="mgmt-source-tag" :class="binding.source">
                          {{ $t('management.product.source_' + binding.source) }}
                        </span>
                      </div>
                      <span v-if="binding.git_url" class="mgmt-repo-url">{{ binding.git_url }}</span>
                    </div>
                  </td>
                  <td>
                    <span class="mgmt-tag" :class="binding.repo_type === 'CUSTOM' ? 'custom' : 'ootb'">
                      {{ binding.repo_type === 'CUSTOM'
                        ? $t('management.repository.type_custom')
                        : $t('management.repository.type_ootb') }}
                    </span>
                  </td>
                  <td>
                    <span class="mgmt-ref-badge">
                      <TagIcon v-if="binding.ref_type === 'TAG'" class="w-4 h-4" />
                      <GitBranch v-else class="w-4 h-4" />
                      <span class="mgmt-ref-text">
                        {{ binding.ref_type === 'TAG' ? $t('management.product.ref_tag') + ' · ' : '' }}{{ binding.ref_name }}
                      </span>
                    </span>
                  </td>
                  <td v-if="canManage">
                    <div class="row-actions">
                      <template v-if="binding.source === 'baseline'">
                        <IconActionButton
                          :icon="Pencil"
                          :title="$t('management.product.override_baseline_repo')"
                          :disabled="overrideSaving"
                          @click="openOverride(version, binding)"
                        />
                        <IconActionButton
                          :icon="Trash2"
                          :title="$t('management.product.exclude_baseline_repo')"
                          tone="danger"
                          :disabled="excludingRepoId === binding.repository_id"
                          @click="excludeBaselineRepo(version, binding.repository_id)"
                        />
                      </template>
                      <template v-else>
                        <IconActionButton
                          :icon="Pencil"
                          :title="$t('management.product.edit_binding_ref')"
                          :disabled="savingRefBindingId === binding.id"
                          @click="openEditBinding(version, binding)"
                        />
                        <IconActionButton
                          :icon="Trash2"
                          :title="$t('common.delete')"
                          tone="danger"
                          @click="unbindTarget = { version, repositoryId: binding.repository_id }"
                        />
                      </template>
                    </div>
                  </td>
                </tr>
                <tr
                  v-if="editingBinding
                    && editingBinding.versionId === version.id
                    && editingBinding.bindingId === binding.id"
                  class="mgmt-binding-edit-row"
                >
                  <td class="mgmt-repo-name">{{ binding.repository_name }}</td>
                  <td colspan="2">
                    <RefNameInput
                      :model-value="editingBinding.ref"
                      :repository-id="binding.repository_id"
                      @update:model-value="updateEditingRef"
                    />
                  </td>
                  <td v-if="canManage">
                    <div class="row-actions">
                      <IconActionButton
                        :icon="Check"
                        :title="$t('common.save')"
                        tone="primary"
                        :disabled="savingRefBindingId === binding.id"
                        @click="saveBindingRef(version)"
                      />
                      <IconActionButton
                        :icon="X"
                        :title="$t('common.cancel')"
                        :disabled="savingRefBindingId === binding.id"
                        @click="cancelEditBinding"
                      />
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>

          <div v-if="filteredBindings(version).length > repoPageSize" class="mgmt-pagination">
            <button class="btn-secondary" :disabled="repoPage <= 1" @click="goRepoPage(version, -1)">
              {{ $t('workspaces.queue.prev_page') }}
            </button>
            <span class="text-muted">{{ repoPage }} / {{ repoTotalPages(version) }}</span>
            <button class="btn-secondary" :disabled="repoPage >= repoTotalPages(version)" @click="goRepoPage(version, 1)">
              {{ $t('workspaces.queue.next_page') }}
            </button>
          </div>

          <!-- Pending bindings awaiting ref configuration -->
          <div v-if="canManage && pickerTargetVersionId === version.id && selectedRepoIds.length > 0" class="mgmt-pending">
            <p class="mgmt-hint">{{ $t('management.product.binding_validate_hint') }}</p>
            <div v-for="repoId in selectedRepoIds" :key="repoId" class="mgmt-pending-row">
              <span class="mgmt-pending-name">{{ repoName(repoId) }}</span>
              <RefNameInput
                :model-value="ensureRef(repoId)"
                :repository-id="repoId"
                @update:model-value="updatePendingRef(repoId, $event)"
              />
            </div>
            <div class="mgmt-modal-actions">
              <button class="btn-secondary" :disabled="savingBinding" @click="cancelPendingBindings">
                {{ $t('common.cancel') }}
              </button>
              <button class="btn-primary" :disabled="savingBinding" @click="saveBindings">
                {{ savingBinding ? $t('management.common.saving') : $t('management.common.save') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑版本弹窗 -->
    <Teleport to="body">
      <div v-if="formVisible" class="mgmt-modal-overlay" @pointerdown.self="formVisible = false">
        <div class="mgmt-modal glass-panel">
          <h3>{{ editingVersion ? $t('management.product.edit_version') : $t('management.product.add_version') }}</h3>

          <div class="mgmt-form-grid">
            <div class="mgmt-field">
              <label>{{ $t('management.product.version_no') }}</label>
              <input v-model="versionForm.version_no" class="mgmt-input" type="text" />
            </div>
            <div class="mgmt-field">
              <label>{{ $t('management.common.status') }}</label>
              <BaseSelect v-model="versionForm.status" :options="versionStatusOptions" />
            </div>
            <div v-if="!editingVersion" class="mgmt-field full">
              <label>{{ $t('management.product.repo_init_mode') }}</label>
              <BaseSelect v-model="versionForm.repo_init_mode" :options="repoInitModeOptions" />
            </div>
            <div v-if="!editingVersion && product?.product_type === 'CUSTOM'" class="mgmt-field full">
              <label>{{ $t('management.product.baseline_product_version') }}</label>
              <BaseSelect
                v-model="versionForm.baseline_product_version_id"
                :options="baselineVersionOptions"
                :placeholder="$t('management.product.select_baseline_version')"
              />
              <p class="mgmt-hint">{{ $t('management.product.baseline_version_hint') }}</p>
            </div>
            <div v-if="!editingVersion && versionForm.repo_init_mode === 'product_base'" class="mgmt-field">
              <label>{{ $t('management.product.inherit_ref_type') }}</label>
              <BaseSelect v-model="versionForm.inherit_ref_type" :options="refTypeOptions" />
            </div>
            <div v-if="!editingVersion && versionForm.repo_init_mode === 'product_base'" class="mgmt-field">
              <label>{{ $t('management.product.inherit_ref_name') }}</label>
              <input
                v-model="versionForm.inherit_ref_name"
                class="mgmt-input"
                type="text"
                :placeholder="$t('management.product.inherit_ref_name_placeholder')"
              />
              <p class="mgmt-hint">{{ $t('management.product.inherit_ref_hint') }}</p>
            </div>
            <div v-if="!editingVersion && versionForm.repo_init_mode === 'from_version'" class="mgmt-field full">
              <label>{{ $t('management.product.evolve_from') }}</label>
              <BaseSelect v-model="versionForm.from_version_id" :options="evolutionOptions" />
              <p class="mgmt-hint">{{ $t('management.product.evolve_from_hint') }}</p>
            </div>
            <p v-if="!editingVersion && versionForm.repo_init_mode === 'product_base'" class="mgmt-hint full">
              {{ $t('management.product.base_repo_count_hint', { count: product?.base_repos.length ?? 0 }) }}
            </p>
            <div class="mgmt-field">
              <label>{{ $t('management.product.release_date') }}</label>
              <el-date-picker
                v-model="versionForm.release_date"
                type="date"
                value-format="YYYY-MM-DD"
                :placeholder="$t('management.product.release_date_placeholder')"
                class="mgmt-date-picker"
              />
            </div>
            <div class="mgmt-field full">
              <label>{{ $t('management.product.version_description') }}</label>
              <textarea v-model="versionForm.description" class="mgmt-input" rows="2"></textarea>
            </div>
          </div>

          <div class="mgmt-modal-actions">
            <button class="btn-secondary" :disabled="savingVersion" @click="formVisible = false">
              {{ $t('common.cancel') }}
            </button>
            <button class="btn-primary" :disabled="savingVersion" @click="saveVersion">
              {{ savingVersion ? $t('management.common.saving') : $t('management.common.save') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 统一变更版本内所有仓库的分支 / Tag -->
    <Teleport to="body">
      <div v-if="batchRefVersionId" class="mgmt-modal-overlay" @pointerdown.self="closeBatchRef">
        <div class="mgmt-modal glass-panel">
          <h3>{{ $t('management.product.batch_update_ref') }}</h3>
          <div class="mgmt-form-grid">
            <div class="mgmt-field">
              <label>{{ $t('management.product.batch_scope') }}</label>
              <BaseSelect v-model="batchScope" :options="batchScopeOptions" />
            </div>
            <div class="mgmt-field">
              <label>{{ $t('management.product.inherit_ref_type') }}</label>
              <BaseSelect v-model="batchRef.ref_type" :options="refTypeOptions" />
            </div>
            <div class="mgmt-field">
              <label>{{ $t('management.product.inherit_ref_name') }}</label>
              <input
                v-model="batchRef.ref_name"
                class="mgmt-input"
                type="text"
                :placeholder="$t('management.product.inherit_ref_name_placeholder')"
              />
            </div>
          </div>
          <p class="mgmt-hint">{{ $t('management.product.batch_update_ref_hint') }}</p>
          <div class="mgmt-modal-actions">
            <button class="btn-secondary" :disabled="batchSaving" @click="closeBatchRef">
              {{ $t('common.cancel') }}
            </button>
            <button class="btn-primary" :disabled="batchSaving" @click="saveBatchRef">
              {{ batchSaving ? $t('management.common.saving') : $t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 覆盖单个基线仓库的分支 / Tag -->
    <Teleport to="body">
      <div v-if="overrideTarget" class="mgmt-modal-overlay" @pointerdown.self="closeOverride">
        <div class="mgmt-modal glass-panel">
          <h3>{{ $t('management.product.override_baseline_repo') }}</h3>
          <p class="mgmt-hint">{{ overrideTarget.repositoryName }}</p>
          <RefNameInput
            :model-value="overrideRef"
            :repository-id="overrideTarget.repositoryId"
            @update:model-value="updateOverrideRef"
          />
          <div class="mgmt-modal-actions">
            <button class="btn-secondary" :disabled="overrideSaving" @click="closeOverride">
              {{ $t('common.cancel') }}
            </button>
            <button class="btn-primary" :disabled="overrideSaving" @click="saveOverride">
              {{ overrideSaving ? $t('management.common.saving') : $t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 查看引用了该基线版本的定制产品版本 -->
    <Teleport to="body">
      <div v-if="customVersionsModal" class="mgmt-modal-overlay" @pointerdown.self="closeCustomVersionsModal">
        <div class="mgmt-modal mgmt-modal-wide glass-panel">
          <h3>{{ $t('management.product.custom_versions_modal_title', { version: customVersionsModal.title }) }}</h3>
          <p class="mgmt-hint">{{ $t('management.product.custom_versions_hint') }}</p>
          <div class="mgmt-modal-list">
            <a
              v-for="item in customVersionsModal.items"
              :key="item.id"
              class="mgmt-modal-list-item"
              href="javascript:void(0)"
              @click="jumpToCustomVersion(item)"
            >
              <span class="mgmt-modal-list-name">{{ item.product_name }}</span>
              <span class="mgmt-modal-list-sub">{{ item.product_code || '' }} · {{ item.version_no }}</span>
            </a>
            <div v-if="customVersionsModal.items.length === 0" class="mgmt-empty">
              {{ $t('management.common.empty') }}
            </div>
          </div>
          <div class="mgmt-modal-actions">
            <button class="btn-secondary" @click="closeCustomVersionsModal">
              {{ $t('common.close') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <RepoGroupPicker
      :show="pickerVisible"
      :exclude-ids="pickerTargetVersionId
        ? (versions.find((v) => v.id === pickerTargetVersionId)?.repo_bindings ?? []).map((b) => b.repository_id)
        : []"
      :allowed-repo-types="allowedRepoTypes"
      v-model="selectedRepoIds"
      @close="cancelPicker"
      @confirm="confirmPicker"
    />

    <ConfirmActionModal
      :show="Boolean(deletingVersion)"
      :title="$t('management.product.versions_title')"
      :message="$t('management.product.delete_version_confirm', { version: deletingVersion?.version_no ?? '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="deletingVersionLoading"
      @cancel="deletingVersion = null"
      @confirm="confirmDeleteVersion"
    />

    <ConfirmActionModal
      :show="Boolean(unbindTarget)"
      :title="$t('management.product.bindings_title')"
      :message="$t('management.product.unbind_confirm', {
        name: unbindTarget
          ? versions
              .find((v) => v.id === unbindTarget!.version.id)
              ?.repo_bindings.find((b) => b.repository_id === unbindTarget!.repositoryId)
              ?.repository_name ?? ''
          : '',
      })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="unbinding"
      @cancel="unbindTarget = null"
      @confirm="confirmUnbind"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.mgmt-section-head .btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.version-card {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 0.9rem 1rem;
  background: rgba(248, 250, 252, 0.6);
}

.version-card-head {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.version-no {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 1rem;
  font-weight: 700;
  color: #1e3a8a;
}

.version-release {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.8rem;
  color: #64748b;
}

.version-release-icon {
  width: 0.9rem;
  height: 0.9rem;
  color: #94a3b8;
}

.version-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin-left: auto;
}

.version-desc {
  margin: 0.5rem 0 0;
  font-size: 0.82rem;
  color: #64748b;
}

.version-baseline-info {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: #475569;
}

.mgmt-link {
  color: #1d4ed8;
  cursor: pointer;
  text-decoration: none;
  border-bottom: 1px dashed #93c5fd;
}

.mgmt-link:hover {
  color: #1e40af;
  border-bottom-style: solid;
}

.version-custom-inheritors {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem 0.5rem;
  margin-top: 0.5rem;
  font-size: 0.78rem;
}

.version-custom-inheritors-title {
  font-weight: 600;
  color: #475569;
}

.mgmt-modal-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.75rem;
  max-height: 50vh;
  overflow-y: auto;
}

.mgmt-modal-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.55rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  cursor: pointer;
  text-decoration: none;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.mgmt-modal-list-item:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.mgmt-modal-list-name {
  font-weight: 600;
  color: #1d4ed8;
}

.mgmt-modal-list-sub {
  font-size: 0.78rem;
  color: #64748b;
}

.version-bindings {
  margin-top: 0.75rem;
  border-top: 1px dashed #e2e8f0;
  padding-top: 0.6rem;
}

.version-bindings-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.4rem;
}

.version-bindings-title {
  font-size: 0.8rem;
  font-weight: 700;
  color: #475569;
}

.version-bind-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.78rem;
  padding: 0.25rem 0.55rem;
}

.version-bind-tools {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.version-bind-filter {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}

.version-repo-search {
  width: 220px;
  padding: 0.35rem 0.6rem;
  font-size: 0.8rem;
}

.version-empty {
  padding: 1rem;
}

.mgmt-repo-cell {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.mgmt-repo-name-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.mgmt-source-tag {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 0.05rem 0.4rem;
  border-radius: 4px;
  background: #f1f5f9;
  color: #64748b;
}

.mgmt-source-tag.baseline {
  background: #eff6ff;
  color: #1d4ed8;
}

.mgmt-source-tag.custom {
  background: #fffbeb;
  color: #92400e;
}

.mgmt-source-tag.custom_override {
  background: #ecfdf5;
  color: #047857;
}

.mgmt-repo-name {
  font-weight: 600;
  color: #334155;
}

.mgmt-repo-url {
  font-size: 0.72rem;
  color: #94a3b8;
  word-break: break-all;
}

.mgmt-ref-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  color: #475569;
}

.mgmt-ref-text {
  white-space: nowrap;
}

.mgmt-pending {
  margin-top: 0.75rem;
  border-top: 1px solid #e2e8f0;
  padding-top: 0.6rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.mgmt-pending-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.mgmt-pending-name {
  width: 180px;
  flex-shrink: 0;
  font-weight: 600;
  font-size: 0.84rem;
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mgmt-date-picker {
  width: 100%;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
