<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Loader2, ShieldCheck } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import { createRepository, updateRepository, validateRepositoryAccess } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { Repository, RepoGroupTreeNode } from '@/types/management'

const props = withDefaults(defineProps<{
  show: boolean;
  repository?: Repository | null;
  groups: RepoGroupTreeNode[];
  defaultGroupId?: string | null;
}>(), {
  repository: null,
  groups: () => [],
  defaultGroupId: null,
})

const emit = defineEmits<{
  (e: 'saved', repository: Repository): void;
  (e: 'cancel'): void;
}>()

const { t } = useI18n()

const isEditing = computed(() => Boolean(props.repository))

const form = reactive<{
  name: string;
  git_url: string;
  repo_type: string;
  default_branch: string;
  group_id: string | null;
  description: string;
}>({
  name: '',
  git_url: '',
  repo_type: 'OOTB',
  default_branch: '',
  group_id: null,
  description: '',
})

const saving = ref(false)
const validating = ref(false)

const repoTypeOptions = computed(() => [
  { label: t('management.repository.type_ootb'), value: 'OOTB' },
  { label: t('management.repository.type_custom'), value: 'CUSTOM' },
])

const flattenedGroups = computed(() => {
  const result: { id: string; name: string }[] = []
  const walk = (nodes: RepoGroupTreeNode[], prefix: string) => {
    for (const node of nodes) {
      if (node.id !== null) {
        result.push({ id: node.id, name: prefix ? prefix + ' / ' + node.name : node.name })
        walk(node.children, node.name)
      }
    }
  }
  walk(props.groups, '')
  return result
})

const groupOptions = computed(() => {
  const options: { label: string; value: string | null }[] = [
    { label: t('management.repository.no_group'), value: null },
  ]
  for (const group of flattenedGroups.value) {
    options.push({ label: group.name, value: group.id })
  }
  return options
})

const resetForm = () => {
  form.name = props.repository?.name ?? ''
  form.git_url = props.repository?.git_url ?? ''
  form.repo_type = props.repository?.repo_type ?? 'OOTB'
  form.default_branch = props.repository?.default_branch ?? ''
  form.group_id = isEditing.value
    ? (props.repository?.group_id ?? null)
    : (props.defaultGroupId ?? null)
  form.description = props.repository?.description ?? ''
}

watch(() => props.show, (visible) => {
  if (visible) {
    resetForm()
  }
})

const canSubmit = computed(
  () => form.name.trim().length > 0 && form.git_url.trim().length > 0 && !saving.value,
)

const handleValidate = async () => {
  if (!form.git_url.trim()) {
    ElMessage.error(t('management.common.required'))
    return
  }
  validating.value = true
  try {
    const result = await validateRepositoryAccess(form.git_url.trim())
    ElMessage.success(t('management.repository.validate_success', {
      branch: result.branch_count ?? 0,
      tag: result.tag_count ?? 0,
    }))
  } catch (err) {
    ElMessage.error(
      t('management.repository.validate_failed') + ': ' + formatApiError(err, '', t),
    )
  } finally {
    validating.value = false
  }
}

const handleSave = async () => {
  if (!canSubmit.value) {
    ElMessage.error(t('management.common.required'))
    return
  }
  saving.value = true
  try {
    if (isEditing.value) {
      const updated = await updateRepository(props.repository!.id, {
        name: form.name.trim(),
        git_url: form.git_url.trim(),
        repo_type: form.repo_type,
        default_branch: form.default_branch.trim(),
        group_id: form.group_id,
        description: form.description.trim() || null,
      })
      emit('saved', updated)
    } else {
      const created = await createRepository({
        name: form.name.trim(),
        git_url: form.git_url.trim(),
        repo_type: form.repo_type,
        default_branch: form.default_branch.trim(),
        group_id: form.group_id,
        description: form.description.trim() || null,
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
    <div class="mgmt-modal glass-panel">
      <h3>{{ isEditing ? $t('management.repository.edit') : $t('management.repository.create') }}</h3>

      <div class="mgmt-form-grid">
        <div class="mgmt-field">
          <label>{{ $t('management.repository.name') }}</label>
          <input v-model="form.name" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.repository.repo_type') }}</label>
          <BaseSelect v-model="form.repo_type" :options="repoTypeOptions" />
        </div>

        <div class="mgmt-field full">
          <label>{{ $t('management.repository.git_url') }}</label>
          <input v-model="form.git_url" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.repository.default_branch') }}</label>
          <input v-model="form.default_branch" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.repository.group') }}</label>
          <BaseSelect v-model="form.group_id" :options="groupOptions" />
        </div>

        <div class="mgmt-field full">
          <label>{{ $t('management.common.description') }}</label>
          <textarea v-model="form.description" class="mgmt-input" rows="3"></textarea>
        </div>
      </div>

      <div v-if="!isEditing" class="mgmt-validate-row">
        <button class="btn-secondary" :disabled="validating" @click="handleValidate">
          <Loader2 v-if="validating" class="mgmt-validate-icon is-spin" />
          <ShieldCheck v-else class="mgmt-validate-icon" />
          {{ $t('management.repository.validate_access') }}
        </button>
        <span class="mgmt-hint">{{ $t('management.repository.validate_access_hint') }}</span>
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
</template>

<style scoped>
.mgmt-validate-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1rem;
}

.mgmt-validate-icon {
  width: 1rem;
  height: 1rem;
}

.mgmt-validate-icon.is-spin {
  animation: mgmt-spin 1s linear infinite;
}

@keyframes mgmt-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>

<style scoped src="@/styles/management/management-shared.css"></style>
