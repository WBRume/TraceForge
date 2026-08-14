<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import RepoPickerDialog from '@/components/management/RepoPickerDialog.vue'
import BranchSelect from '@/components/management/BranchSelect.vue'
import { associateProjectRepo, dissociateProjectRepo } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { ProjectDetail, ProjectRepoAssociation, Repository } from '@/types/management'

const props = defineProps<{
  project: ProjectDetail;
  canManage: boolean;
}>()

const emit = defineEmits<{
  (e: 'changed'): void;
}>()

const { t } = useI18n()

const associatedRepoIds = computed(
  () => new Set(props.project.repo_associations.map((a) => a.repository_id))
)

const repoTypeTag = (repoType: string | null): string =>
  repoType === 'OOTB' ? 'ootb' : repoType === 'CUSTOM' ? 'custom' : 'gray'

const repoTypeLabel = (repoType: string | null): string => {
  if (repoType === 'OOTB') return t('management.repository.type_ootb')
  if (repoType === 'CUSTOM') return t('management.repository.type_custom')
  return repoType ?? '-'
}

// 添加关联
const pickerShow = ref(false)
const pendingRepo = ref<Repository | null>(null)
const pendingBranch = ref<string>('')
const associating = ref(false)

const handlePick = (repository: Repository) => {
  pendingRepo.value = repository
  pendingBranch.value = repository.default_branch ?? ''
  pickerShow.value = false
}

const confirmAssociate = async () => {
  if (!pendingRepo.value) return
  associating.value = true
  try {
    await associateProjectRepo(props.project.id, {
      repository_id: pendingRepo.value.id,
      branch_name: pendingBranch.value || null,
    })
    pendingRepo.value = null
    pendingBranch.value = ''
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    associating.value = false
  }
}

const cancelAssociate = () => {
  if (associating.value) return
  pendingRepo.value = null
  pendingBranch.value = ''
}

// 解除关联
const removing = ref<ProjectRepoAssociation | null>(null)
const removeLoading = ref(false)

const confirmRemove = async () => {
  if (!removing.value) return
  removeLoading.value = true
  try {
    await dissociateProjectRepo(props.project.id, removing.value.repository_id)
    removing.value = null
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    removeLoading.value = false
  }
}
</script>

<template>
  <div class="mgmt-card">
    <div class="mgmt-card-header">
      <h3>{{ $t('management.project.repos_title') }}</h3>
      <button v-if="canManage" class="btn-primary" @click="pickerShow = true">
        <Plus class="w-4 h-4" /> {{ $t('management.project.add_association') }}
      </button>
    </div>

    <table v-if="project.repo_associations.length > 0" class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.common.name') }}</th>
          <th>{{ $t('management.repository.git_url') }}</th>
          <th>{{ $t('management.common.type') }}</th>
          <th>{{ $t('management.common.branch') }}</th>
          <th v-if="canManage">{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="assoc in project.repo_associations" :key="assoc.id">
          <td>{{ assoc.repository_name || assoc.repository_id }}</td>
          <td class="mgmt-url-cell">{{ assoc.git_url || '-' }}</td>
          <td>
            <span class="mgmt-tag" :class="repoTypeTag(assoc.repo_type)">
              {{ repoTypeLabel(assoc.repo_type) }}
            </span>
          </td>
          <td class="mgmt-code-cell">{{ assoc.branch_name || '-' }}</td>
          <td v-if="canManage">
            <div class="row-actions">
              <button
                class="btn-ghost mgmt-assoc-remove"
                :title="$t('common.delete')"
                @click="removing = assoc"
              >
                {{ $t('common.delete') }}
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-else class="mgmt-empty">{{ $t('management.project.no_associations') }}</div>

    <RepoPickerDialog
      :show="pickerShow"
      :exclude-ids="Array.from(associatedRepoIds)"
      @pick="handlePick"
      @close="pickerShow = false"
    />

    <!-- 添加确认：选择分支 -->
    <div v-if="pendingRepo" class="mgmt-modal-overlay" @click.self="cancelAssociate">
      <div class="mgmt-modal glass-panel mgmt-assoc-modal">
        <h3>{{ $t('management.project.add_association') }}</h3>
        <p class="mgmt-assoc-repo-name">{{ pendingRepo.name }}</p>
        <div class="mgmt-field">
          <label>{{ $t('management.common.branch') }}</label>
          <BranchSelect v-model="pendingBranch" :repository-id="pendingRepo.id" />
        </div>
        <div class="mgmt-modal-actions">
          <button class="btn-secondary" :disabled="associating" @click="cancelAssociate">
            {{ $t('common.cancel') }}
          </button>
          <button class="btn-primary" :disabled="associating" @click="confirmAssociate">
            {{ associating ? $t('common.saving') : $t('common.confirm') }}
          </button>
        </div>
      </div>
    </div>

    <ConfirmActionModal
      :show="Boolean(removing)"
      :title="$t('management.project.repos_title')"
      :message="$t('management.project.association_remove_confirm', { name: removing?.repository_name || removing?.repository_id || '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="removeLoading"
      @cancel="removing = null"
      @confirm="confirmRemove"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.mgmt-card-header h3 {
  margin: 0;
}

.mgmt-code-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  color: #475569;
}

.mgmt-url-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
  color: #64748b;
  word-break: break-all;
}

.mgmt-assoc-remove {
  font-size: 0.78rem;
  color: #b91c1c;
}

.mgmt-tag.gray {
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.mgmt-assoc-modal {
  max-width: 440px;
}

.mgmt-assoc-repo-name {
  margin: 0 0 1rem;
  font-weight: 600;
  color: #334155;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
</style>
