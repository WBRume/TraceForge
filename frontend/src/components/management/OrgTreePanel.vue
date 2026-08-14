<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus, FolderPlus, Info } from 'lucide-vue-next'
import OrgTreeNodeRow from '@/components/management/OrgTreeNodeRow.vue'
import OrgNodeFormModal from '@/components/management/OrgNodeFormModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { deleteOrgNode, getOrgTree } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { OrgTreeNode } from '@/types/management'

const props = withDefaults(defineProps<{
  canManage: boolean;
  selectedRepoId: string | null;
}>(), {
  selectedRepoId: null,
})

const emit = defineEmits<{
  (e: 'select', nodeId: string | null): void;
  (e: 'changed'): void;
  (e: 'load', nodes: OrgTreeNode[]): void;
}>()

const { t } = useI18n()

const tree = ref<OrgTreeNode[]>([])
const loading = ref(false)

// 当前选中产品线（用于「新建项目组」默认上级）
const selectedProductLineId = ref<string | null>(null)

// 表单弹窗状态
const formVisible = ref(false)
const editingNode = ref<OrgTreeNode | null>(null)
const formParentId = ref<string | null>(null)

// 删除确认状态
const deletingNode = ref<OrgTreeNode | null>(null)
const deleteLoading = ref(false)

const load = async () => {
  loading.value = true
  try {
    const res = await getOrgTree()
    tree.value = res.items ?? []
    emit('load', tree.value)
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}

void load()

const openCreateProductLine = () => {
  editingNode.value = null
  formParentId.value = null
  formVisible.value = true
}

const openCreateProjectGroup = () => {
  editingNode.value = null
  formParentId.value = selectedProductLineId.value
  formVisible.value = true
}

const openEdit = (node: OrgTreeNode) => {
  editingNode.value = node
  formParentId.value = node.parent_id ?? null
  formVisible.value = true
}

const openDelete = (node: OrgTreeNode) => {
  deletingNode.value = node
}

const handleAddChild = (node: OrgTreeNode) => {
  selectedProductLineId.value = node.id
  openCreateProjectGroup()
}

const handleSelectRepo = (repoId: string) => {
  selectedProductLineId.value = null
  emit('select', repoId)
}

const handleFormSaved = () => {
  formVisible.value = false
  emit('changed')
  void load()
}

const handleDeleteConfirm = async () => {
  if (!deletingNode.value?.id) return
  deleteLoading.value = true
  try {
    await deleteOrgNode(deletingNode.value.id)
    ElMessage.success(t('common.success'))
    deletingNode.value = null
    emit('changed')
    void load()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deleteLoading.value = false
  }
}
</script>

<template>
  <div class="mgmt-org-panel glass-panel">
    <div v-if="!canManage" class="mgmt-readonly-banner">
      <Info class="mgmt-org-banner-icon" />
      <span>{{ $t('management.org.readonly_hint') }}</span>
    </div>

    <div v-else class="mgmt-org-actions">
      <button class="btn-secondary" @click="openCreateProductLine">
        <Plus class="mgmt-org-action-icon" />
        {{ $t('management.org.add_product_line') }}
      </button>
      <button class="btn-secondary" @click="openCreateProjectGroup">
        <FolderPlus class="mgmt-org-action-icon" />
        {{ $t('management.org.add_project_group') }}
      </button>
    </div>

    <div v-if="loading" class="mgmt-org-loading mgmt-hint">
      {{ $t('common.loading') }}
    </div>

    <div v-else class="mgmt-org-tree">
      <OrgTreeNodeRow
        v-for="node in tree"
        :key="node.id ?? ('unassigned-' + node.name)"
        :node="node"
        :can-manage="canManage"
        :selected-repo-id="selectedRepoId"
        :depth="0"
        @select-repo="handleSelectRepo"
        @add-child="handleAddChild"
        @edit-node="openEdit"
        @delete-node="openDelete"
      />
    </div>

    <OrgNodeFormModal
      :show="formVisible"
      :node="editingNode"
      :parent-id="formParentId"
      @saved="handleFormSaved"
      @cancel="formVisible = false"
    />

    <ConfirmActionModal
      :show="Boolean(deletingNode)"
      :title="t('management.org.delete_node')"
      :message="$t('management.org.delete_node_confirm', { name: deletingNode?.name ?? '' })"
      :cancel-text="t('common.cancel')"
      :confirm-text="t('common.delete')"
      :loading="deleteLoading"
      :tone="'danger'"
      @cancel="deletingNode = null"
      @confirm="handleDeleteConfirm"
    />
  </div>
</template>

<style scoped>
.mgmt-org-panel {
  display: flex;
  flex-direction: column;
  padding: 1rem;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  max-height: calc(100vh - 140px);
  overflow-y: auto;
}

.mgmt-org-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.mgmt-org-action-icon {
  width: 0.9rem;
  height: 0.9rem;
}

.mgmt-org-banner-icon {
  width: 0.9rem;
  height: 0.9rem;
  flex-shrink: 0;
}

.mgmt-org-loading {
  padding: 0.5rem;
}

.mgmt-org-tree {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
</style>

<style scoped src="@/styles/management/management-shared.css"></style>