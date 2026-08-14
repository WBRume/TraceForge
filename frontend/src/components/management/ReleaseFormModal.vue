<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { X, Plus } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import RepoPickerDialog from '@/components/management/RepoPickerDialog.vue'
import BranchSelect from '@/components/management/BranchSelect.vue'
import {
  createProjectRelease,
  getProduct,
  listProducts,
  updateProjectRelease,
} from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type {
  Product,
  ProductDetail,
  ProjectRelease,
  Repository,
  VersionRepoBinding,
} from '@/types/management'

const props = withDefaults(defineProps<{
  show: boolean;
  projectId: string;
  release?: ProjectRelease | null;
}>(), {
  release: null,
})

const emit = defineEmits<{
  (e: 'saved', release: ProjectRelease): void;
  (e: 'cancel'): void;
}>()

const { t } = useI18n()

const isEditing = computed(() => Boolean(props.release?.id))

interface Option {
  label: string;
  value: any;
}

interface CustomRepo {
  key: string;
  repository_id: string;
  repository_name: string;
  branch_name: string;
}

const form = reactive<{
  release_no: string;
  name: string;
  product_id: string | null;
  product_version_id: string | null;
  status: string;
  release_date: string;
  notes: string;
}>({
  release_no: '',
  name: '',
  product_id: null,
  product_version_id: null,
  status: 'DRAFT',
  release_date: '',
  notes: '',
})

const saving = ref(false)

// 产品 / 版本下拉数据
const products = ref<Product[]>([])
const productOptions = computed<Option[]>(() => [
  { label: t('management.project.release_product') + ' —', value: null },
  ...products.value.map((p) => ({ label: p.name, value: p.id })),
])

const productDetail = ref<ProductDetail | null>(null)
const versions = computed(() => productDetail.value?.versions ?? [])
const versionOptions = computed<Option[]>(() => [
  { label: t('management.project.release_version') + ' —', value: null },
  ...versions.value.map((v) => ({ label: v.version_no, value: v.id })),
])

const ootbBindings = computed<VersionRepoBinding[]>(() => {
  if (!form.product_version_id) return []
  const selectedVersion = versions.value.find((v) => v.id === form.product_version_id)
  return selectedVersion?.repo_bindings ?? []
})

// 定制仓
const customRepos = ref<CustomRepo[]>([])
const pickerShow = ref(false)
let customRepoSeq = 0

const customRepoKeys = computed(() => new Set(customRepos.value.map((r) => r.repository_id)))

const loadProducts = async () => {
  try {
    const res = await listProducts({ page_size: 100 })
    products.value = res.items ?? []
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  }
}

const loadProduct = async (productId: string) => {
  try {
    productDetail.value = await getProduct(productId)
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  }
}

watch(() => form.product_id, (productId) => {
  form.product_version_id = null
  productDetail.value = null
  if (productId) {
    void loadProduct(productId)
  }
})

const resetForm = () => {
  form.release_no = props.release?.release_no ?? ''
  form.name = props.release?.name ?? ''
  form.product_id = props.release?.product_id ?? null
  form.product_version_id = props.release?.product_version_id ?? null
  form.status = props.release?.status ?? 'DRAFT'
  form.release_date = props.release?.release_date?.slice(0, 10) ?? ''
  form.notes = props.release?.notes ?? ''
  customRepos.value = []
  customRepoSeq = 0
  productDetail.value = null
}

watch(
  () => props.show,
  async (visible) => {
    if (!visible) return
    resetForm()
    await loadProducts()
    if (form.product_id) {
      await loadProduct(form.product_id)
    }
  }
)

const statusOptions = computed<Option[]>(() => [
  { label: t('management.project.release_status_draft'), value: 'DRAFT' },
  { label: t('management.project.release_status_published'), value: 'PUBLISHED' },
  { label: t('management.project.release_status_retired'), value: 'RETIRED' },
])

const canSubmit = computed(
  () => form.release_no.trim().length > 0 && form.name.trim().length > 0 && !saving.value
)

// 定制仓选择
const openRepoPicker = () => {
  pickerShow.value = true
}

const handlePickRepo = (repository: Repository) => {
  customRepoSeq += 1
  customRepos.value.push({
    key: repository.id + ':' + customRepoSeq,
    repository_id: repository.id,
    repository_name: repository.name,
    branch_name: repository.default_branch ?? '',
  })
  pickerShow.value = false
}

const removeCustomRepo = (key: string) => {
  customRepos.value = customRepos.value.filter((r) => r.key !== key)
}

const payloadCustomRepos = computed(() =>
  customRepos.value.map((r) => ({
    repository_id: r.repository_id,
    branch_name: r.branch_name,
  }))
)

const toNullable = (value: string): string | null => (value.trim().length > 0 ? value.trim() : null)

const handleSave = async () => {
  if (!canSubmit.value) {
    ElMessage.error(t('management.common.required'))
    return
  }
  saving.value = true
  try {
    if (isEditing.value) {
      const updated = await updateProjectRelease(props.projectId, props.release!.id, {
        release_no: form.release_no.trim(),
        name: form.name.trim(),
        status: form.status,
        release_date: form.release_date ? form.release_date : null,
        notes: toNullable(form.notes),
      })
      emit('saved', updated)
    } else {
      const created = await createProjectRelease(props.projectId, {
        release_no: form.release_no.trim(),
        name: form.name.trim(),
        product_id: form.product_id,
        product_version_id: form.product_version_id,
        status: form.status,
        release_date: form.release_date ? form.release_date : null,
        notes: toNullable(form.notes),
        custom_repos: payloadCustomRepos.value,
      })
      emit('saved', created)
    }
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    saving.value = false
  }
}

const handleCancel = () => {
  if (saving.value) return
  emit('cancel')
}
</script>

<template>
  <div v-if="show" class="mgmt-modal-overlay" @click.self="handleCancel">
    <div class="mgmt-modal glass-panel mgmt-modal-wide">
      <h3>{{ isEditing ? $t('management.project.edit_release') : $t('management.project.add_release') }}</h3>

      <div class="mgmt-form-grid">
        <div class="mgmt-field">
          <label>{{ $t('management.project.release_no') }}</label>
          <input v-model="form.release_no" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.project.release_name') }}</label>
          <input v-model="form.name" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.project.release_product') }}</label>
          <BaseSelect v-model="form.product_id" :options="productOptions" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.project.release_version') }}</label>
          <BaseSelect
            v-model="form.product_version_id"
            :options="versionOptions"
            :disabled="!form.product_id"
          />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.common.status') }}</label>
          <BaseSelect v-model="form.status" :options="statusOptions" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.project.release_date') }}</label>
          <input v-model="form.release_date" class="mgmt-input" type="date" />
        </div>

        <div class="mgmt-field full">
          <label>{{ $t('management.project.release_notes') }}</label>
          <textarea v-model="form.notes" class="mgmt-input" rows="3"></textarea>
        </div>
      </div>

      <div v-if="ootbBindings.length > 0" class="mgmt-release-section">
        <h4>{{ $t('management.project.ootb_preview') }}</h4>
        <ul class="mgmt-ootb-list">
          <li v-for="binding in ootbBindings" :key="binding.id">
            <span class="mgmt-ootb-repo">{{ binding.repository_name }}</span>
            <span class="mgmt-ootb-branch">{{ binding.branch_name }}</span>
          </li>
        </ul>
      </div>

      <div class="mgmt-release-section">
        <div class="mgmt-selection-title">
          <h4>{{ $t('management.project.custom_repos') }}</h4>
          <button class="btn-secondary" @click="openRepoPicker">
            <Plus class="w-4 h-4" /> {{ $t('management.project.add_custom_repo') }}
          </button>
        </div>
        <p class="mgmt-hint">{{ $t('management.project.custom_repos_hint') }}</p>

        <div v-if="customRepos.length > 0" class="mgmt-custom-repos">
          <div v-for="repo in customRepos" :key="repo.key" class="mgmt-custom-repo-row">
            <span class="mgmt-custom-repo-name" :title="repo.repository_id">{{ repo.repository_name }}</span>
            <div class="mgmt-custom-repo-branch">
              <BranchSelect v-model="repo.branch_name" :repository-id="repo.repository_id" />
            </div>
            <button
              class="btn-ghost mgmt-custom-repo-remove"
              :title="$t('common.delete')"
              @click="removeCustomRepo(repo.key)"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <div class="mgmt-modal-actions">
        <button class="btn-secondary" :disabled="saving" @click="handleCancel">
          {{ $t('common.cancel') }}
        </button>
        <button class="btn-primary" :disabled="!canSubmit" @click="handleSave">
          {{ saving ? $t('common.saving') : $t('common.save') }}
        </button>
      </div>
    </div>
  </div>

  <RepoPickerDialog
    :show="pickerShow"
    :exclude-ids="Array.from(customRepoKeys)"
    @pick="handlePickRepo"
    @close="pickerShow = false"
  />
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-modal-wide {
  max-width: 720px;
}

.mgmt-release-section {
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid #e2e8f0;
}

.mgmt-release-section h4 {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
  font-weight: 700;
  color: #334155;
}

.mgmt-selection-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.mgmt-selection-title h4 {
  margin: 0;
}

.mgmt-ootb-list {
  list-style: none;
  margin: 0.5rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.mgmt-ootb-list li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
  color: #475569;
}

.mgmt-ootb-repo {
  font-weight: 600;
}

.mgmt-ootb-branch {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.76rem;
  color: #64748b;
}

.mgmt-custom-repos {
  margin-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.mgmt-custom-repo-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.mgmt-custom-repo-name {
  flex: 1;
  font-size: 0.82rem;
  color: #334155;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mgmt-custom-repo-branch {
  width: 260px;
  flex-shrink: 0;
}

.mgmt-custom-repo-remove {
  flex-shrink: 0;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>