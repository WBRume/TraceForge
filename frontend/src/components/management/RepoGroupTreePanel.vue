<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Info, Plus, Search } from 'lucide-vue-next'
import RepoGroupTreeNodeRow from '@/components/management/RepoGroupTreeNodeRow.vue'
import RepoGroupFormModal from '@/components/management/RepoGroupFormModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { deleteRepoGroup, getRepoGroupTree } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { RepoGroupTreeNode } from '@/types/management'

const props = defineProps<{
  canManage: boolean;
  selectedGroupId: string | null;
}>()

const emit = defineEmits<{
  (e: 'select-group', groupId: string | null): void;
  (e: 'changed'): void;
}>()

const { t } = useI18n()

const tree = ref<RepoGroupTreeNode[]>([])
const loading = ref(false)
const searchKeyword = ref('')

const formVisible = ref(false)
const editingGroup = ref<{ id: string; name: string; parent_id: string | null } | null>(null)
const defaultParentId = ref<string | null>(null)
const lockParent = ref(false)

const deletingGroup = ref<{ id: string; name: string; parent_id: string | null } | null>(null)
const deleteLoading = ref(false)

const load = async () => {
  loading.value = true
  try {
    const res = await getRepoGroupTree()
    tree.value = res.items ?? []
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

const handleChanged = () => {
  void load()
  emit('changed')
}

const handleGroupSaved = () => {
  formVisible.value = false
  handleChanged()
}

const openCreate = () => {
  editingGroup.value = null
  // 从树中选中的仓库组直接作为新组的上级组，且不允许变更；
  // 未选中任何组时允许自由选择上级组。
  defaultParentId.value = props.selectedGroupId
  lockParent.value = props.selectedGroupId !== null
  formVisible.value = true
}

const openEdit = (group: { id: string; name: string; parent_id: string | null }) => {
  editingGroup.value = group
  defaultParentId.value = null
  lockParent.value = false
  formVisible.value = true
}

const openDelete = (group: { id: string; name: string; parent_id: string | null }) => {
  deletingGroup.value = group
}

const handleDeleteConfirm = async () => {
  if (!deletingGroup.value) return
  deleteLoading.value = true
  try {
    await deleteRepoGroup(deletingGroup.value.id)
    deletingGroup.value = null
    ElMessage.success(t('common.success'))
    handleChanged()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deleteLoading.value = false
  }
}

// 树形搜索过滤：仅按仓库组名称匹配；命中的组展示整棵子树，
// 未命中的祖先组仅作为路径保留。
const filteredTree = computed<RepoGroupTreeNode[]>(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return tree.value
  const matchText = (text: string): boolean =>
    String(text || '').toLowerCase().includes(kw)
  const filterNode = (node: RepoGroupTreeNode): RepoGroupTreeNode | null => {
    if (matchText(node.name)) {
      return { ...node }
    }
    const children: RepoGroupTreeNode[] = []
    for (const child of node.children || []) {
      const filtered = filterNode(child)
      if (filtered) children.push(filtered)
    }
    if (children.length === 0) return null
    return {
      ...node,
      repositories: [],
      children,
    }
  }
  return tree.value
    .map(filterNode)
    .filter((node): node is RepoGroupTreeNode => node !== null)
})

const groupedNodes = computed(() => filteredTree.value.filter((node) => node.id !== null))
</script>

<template>
  <div class="mgmt-card mgmt-repo-group-tree">
    <div class="mgmt-repo-group-header">
      <span class="mgmt-repo-group-title">{{ $t('management.repo_group.title') }}</span>
      <button
        v-if="canManage"
        class="btn-ghost mgmt-repo-group-add"
        :title="$t('management.repo_group.add')"
        @click="openCreate"
      >
        <Plus class="mgmt-repo-group-add-icon" />
        {{ $t('management.repo_group.add') }}
      </button>
    </div>

    <div class="mgmt-repo-group-search">
      <Search class="mgmt-repo-group-search-icon" />
      <input
        v-model="searchKeyword"
        class="mgmt-repo-group-search-input"
        type="text"
        :placeholder="$t('management.repo_group.search_placeholder')"
      />
    </div>

    <div v-if="!canManage" class="mgmt-readonly-banner">
      <Info class="w-4 h-4" />
      <span>{{ $t('management.repo_group.readonly_hint') }}</span>
    </div>

    <div v-if="loading" class="mgmt-empty">{{ $t('common.loading') }}</div>

    <template v-else>
      <RepoGroupTreeNodeRow
        v-for="node in groupedNodes"
        :key="node.id ?? node.name"
        :node="node"
        :can-manage="canManage"
        :selected-group-id="selectedGroupId"
        :depth="0"
        @select-group="emit('select-group', $event)"
        @edit-group="openEdit"
        @delete-group="openDelete"
        @changed="handleChanged"
      />

      <div v-if="groupedNodes.length === 0" class="mgmt-empty">
        {{ $t('management.common.empty') }}
      </div>
    </template>

    <RepoGroupFormModal
      :show="formVisible"
      :group="editingGroup"
      :parent-id="defaultParentId"
      :lock-parent="lockParent"
      :groups="groupedNodes"
      @saved="handleGroupSaved"
      @cancel="formVisible = false"
    />

    <ConfirmActionModal
      :show="Boolean(deletingGroup)"
      :title="$t('management.repo_group.delete')"
      :message="$t('management.repo_group.delete_confirm', { name: deletingGroup?.name ?? '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.delete')"
      tone="danger"
      :loading="deleteLoading"
      @cancel="deletingGroup = null"
      @confirm="handleDeleteConfirm"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.mgmt-repo-group-tree {
  display: flex;
  flex-direction: column;
}

.mgmt-repo-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.mgmt-repo-group-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e3a8a;
}

.mgmt-repo-group-add {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  padding: 0.35rem 0.6rem;
}

.mgmt-repo-group-add.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

.mgmt-repo-group-add-icon {
  width: 0.85rem;
  height: 0.85rem;
}

.mgmt-repo-group-search {
  position: relative;
  margin-bottom: 0.75rem;
}

.mgmt-repo-group-search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px 8px 32px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-family: inherit;
  font-size: 0.82rem;
  color: #334155;
  background: rgba(255, 255, 255, 0.8);
  outline: none;
  transition: border-color 0.2s;
}

.mgmt-repo-group-search-input:focus {
  border-color: #0ea5e9;
}

.mgmt-repo-group-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 0.9rem;
  height: 0.9rem;
  color: #94a3b8;
  pointer-events: none;
}

.mgmt-group-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.45rem 0.5rem;
  border-radius: 8px;
  cursor: pointer;
  color: #334155;
  font-weight: 600;
  font-size: 0.88rem;
}

.mgmt-group-row:hover {
  background: rgba(14, 165, 233, 0.06);
}

.mgmt-group-row.is-selected {
  background: rgba(14, 165, 233, 0.12);
  color: #0ea5e9;
}

.mgmt-group-icon {
  width: 1rem;
  height: 1rem;
  color: #64748b;
  flex-shrink: 0;
}

.mgmt-group-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
