<!--
VersionRepoBindingPanel: list existing version-repo bindings and add new
ones via RepoPickerDialog + BranchSelect.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import RepoPickerDialog from '@/components/management/RepoPickerDialog.vue'
import BranchSelect from '@/components/management/BranchSelect.vue'
import { bindVersionRepo, unbindVersionRepo } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { ProductVersion, Repository, VersionRepoBinding } from '@/types/management'

const props = defineProps<{
  productId: string
  version: ProductVersion
  canManage: boolean
}>()

const emit = defineEmits<{
  (e: 'changed'): void
}>()

const { t } = useI18n()

const showPicker = ref(false)
const selectedRepo = ref<Repository | null>(null)
const selectedBranch = ref('')
const bindingLoading = ref(false)

const unbindTarget = ref<VersionRepoBinding | null>(null)
const unbindLoading = ref(false)

const boundRepoIds = computed(() => props.version.repo_bindings.map((b) => b.repository_id))

const bindingReady = computed(() => Boolean(selectedRepo.value && selectedBranch.value))

const openPicker = () => {
  selectedRepo.value = null
  selectedBranch.value = ''
  showPicker.value = true
}

const onPickRepo = (repo: Repository) => {
  selectedRepo.value = repo
  selectedBranch.value = ''
}

const confirmBind = async () => {
  if (!selectedRepo.value || !selectedBranch.value) return
  bindingLoading.value = true
  try {
    await bindVersionRepo(props.productId, props.version.id, {
      repository_id: selectedRepo.value.id,
      branch_name: selectedBranch.value,
    })
    ElMessage.success(t('management.common.save'))
    selectedRepo.value = null
    selectedBranch.value = ''
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    bindingLoading.value = false
  }
}

const confirmUnbind = async () => {
  if (!unbindTarget.value) return
  unbindLoading.value = true
  try {
    await unbindVersionRepo(props.productId, props.version.id, unbindTarget.value.repository_id)
    ElMessage.success(t('management.common.deleted'))
    unbindTarget.value = null
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    unbindLoading.value = false
  }
}
</script>

<template>
  <div class="mgmt-binding">
    <h4>{{ $t('management.product.bindings_title') }}</h4>

    <div v-if="version.repo_bindings.length === 0" class="mgmt-empty">
      {{ $t('management.product.no_bindings') }}
    </div>

    <table v-else class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.common.name') }}</th>
          <th>{{ $t('management.repository.git_url') }}</th>
          <th>{{ $t('management.common.type') }}</th>
          <th>{{ $t('management.common.branch') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="binding in version.repo_bindings" :key="binding.id">
          <td>{{ binding.repository_name }}</td>
          <td>{{ binding.git_url || '-' }}</td>
          <td>
            <span
              v-if="binding.repo_type"
              class="mgmt-tag"
              :class="binding.repo_type === 'OOTB' ? 'ootb' : 'custom'"
            >
              {{ binding.repo_type === 'OOTB'
                ? $t('management.repository.type_ootb')
                : $t('management.repository.type_custom') }}
            </span>
            <span v-else>-</span>
          </td>
          <td>
            <span class="mgmt-branch-badge">{{ binding.branch_name }}</span>
          </td>
          <td>
            <DeleteActionButton
              mode="icon"
              :title="$t('common.delete')"
              :disabled="!canManage"
              @click="unbindTarget = binding"
            />
          </td>
        </tr>
      </tbody>
    </table>

    <template v-if="canManage">
      <button class="btn-secondary mgmt-binding-add" @click="openPicker">
        <Plus class="w-4 h-4" />
        {{ $t('management.product.add_binding') }}
      </button>

      <div v-if="selectedRepo" class="mgmt-binding-form glass-panel">
        <div class="mgmt-field">
          <label>{{ $t('management.product.binding_repo') }}</label>
          <div class="mgmt-binding-repo-name">{{ selectedRepo.name }}</div>
        </div>
        <div class="mgmt-field">
          <label>{{ $t('management.product.binding_branch') }}</label>
          <BranchSelect v-model="selectedBranch" :repository-id="selectedRepo.id" />
        </div>
        <p class="mgmt-hint">{{ $t('management.product.binding_validate_hint') }}</p>
        <button class="btn-primary" :disabled="!bindingReady || bindingLoading" @click="confirmBind">
          {{ bindingLoading ? $t('management.common.saving') : $t('management.product.add_binding') }}
        </button>
      </div>
    </template>

    <RepoPickerDialog
      :show="showPicker"
      :exclude-ids="boundRepoIds"
      @pick="onPickRepo"
      @close="showPicker = false"
    />

    <ConfirmActionModal
      :show="Boolean(unbindTarget)"
      :title="$t('management.product.bindings_title')"
      :message="$t('management.product.unbind_confirm', {
        name: unbindTarget?.repository_name ?? '',
      })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="unbindLoading"
      @cancel="unbindTarget = null"
      @confirm="confirmUnbind"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-binding {
  padding: 0.75rem 0.9rem;
  border-top: 1px solid #f1f5f9;
}

.mgmt-binding h4 {
  margin: 0 0 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--color-primary-900);
}

.mgmt-binding-add {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.75rem;
}

.mgmt-binding-form {
  margin-top: 0.75rem;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.mgmt-binding-repo-name {
  padding: 9px 13px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 0.92rem;
  color: #334155;
}

.mgmt-branch-badge {
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #0f766e;
  background: #f0fdfa;
  border: 1px solid #99f6e4;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
