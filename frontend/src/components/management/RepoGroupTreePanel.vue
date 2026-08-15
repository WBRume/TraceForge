<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Folder, GitBranch, Info, Plus, Search } from 'lucide-vue-next'
import RepoGroupTreeNodeRow from '@/components/management/RepoGroupTreeNodeRow.vue'
import RepoGroupFormModal from '@/components/management/RepoGroupFormModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { deleteRepoGroup, getRepoGroupTree } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { RepoGroupTreeNode } from '@/types/management'

const props = defineProps<{
  canManage: boolean;
  selectedGroupId: string | null;
  selectedRepoId: string | null;
  showUnassigned: boolean;
}>()

const emit = defineEmits<{
  (e: 'select-group', groupId: string | null): void;
  (e: 'select-repo', repositoryId: string): void;
  (e: 'changed'): void;
}>()

const { t } = useI18n()

const tree = ref<RepoGroupTreeNode[]>([])
const loading = ref(false)
const searchKeyword = ref('')

const formVisible = ref(false)
const editingGroup = ref<{ id: string; name: string; parent_id: string | null } | null>(null)
const defaultParentId = ref<string | null>(null)

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

const openCreate = () => {
  editingGroup.value = null
  defaultParentId.value = props.selectedGroupId
  formVisible.value = true
}

const openEdit = (group: { id: string; name: string; parent_id: string | null }) => {
  editingGroup.value = group
  defaultParentId.value = null
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
    handleChanged()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deleteLoading.value = false
  }
}

// 树形搜索过滤：组名匹配时保留整棵子树；否则仅保留名称匹配的仓库与匹配的子孙组
const filteredTree = computed<RepoGroupTreeNode[]>(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return tree.value
  const matchText = (text: string): boolean =>
    String(text || '').toLowerCase().includes(kw)
  const filterNode = (node: RepoGroupTreeNode): RepoGroupTreeNode | null => {
    const nameMatch = matchText(node.name)
    const repos = (node.repositories || []).filter((repo) => matchText(repo.name))
    const children: RepoGroupTreeNode[] = []
    for (const child of node.children || []) {
      const filtered = filterNode(child)
      if (filtered) children.push(filtered)
    }
    if (!nameMatch && repos.length === 0 && children.length === 0) return null
    return {
      ...node,
      repositories: nameMatch ? (node.repositories || []) : repos,
      children,
    }
  }
  return tree.value
    .map(filterNode)
    .filter((node): node is RepoGroupTreeNode => node !== null)
})

const unassignedGroups = computed(() => filteredTree.value.filter((node) => node.id === null))
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
      <div
        class="mgmt-group-row mgmt-group-unassigned"
        :class="{ 'is-selected': showUnassigned && !selectedRepoId }"
        @click="emit('select-group', null)"
      >
        <Folder class="mgmt-group-icon" />
        <span class="mgmt-group-name">{{ $t('management.repo_group.unassigned') }}</span>
      </div>

      <template v-for="(node, index) in unassignedGroups" :key="'unassigned-' + index">
        <div
          v-for="repo in node.repositories"
          :key="repo.id"
          class="mgmt-repo-row"
          :class="{ 'is-selected': selectedRepoId === repo.id }"
          @click="emit('select-repo', repo.id)"
        >
          <GitBranch class="mgmt-repo-icon" />
          <span class="mgmt-repo-name">{{ repo.name }}</span>
        </div>
      </template>

      <RepoGroupTreeNodeRow
        v-for="node in groupedNodes"
        :key="node.id ?? node.name"
        :node="node"
        :can-manage="canManage"
        :selected-group-id="selectedGroupId"
        :selected-repo-id="selectedRepoId"
        :depth="0"
        @select-group="emit('select-group', $event)"
        @select-repo="emit('select-repo', $event)"
        @edit-group="openEdit"
        @delete-group="openDelete"
        @changed="handleChanged"
      />

      <div v-if="groupedNodes.length === 0 && unassignedGroups.length === 0" class="mgmt-empty">
        {{ $t('management.common.empty') }}
      </div>
    </template>

    <RepoGroupFormModal
      :show="formVisible"
      :group="editingGroup"
      :parent-id="defaultParentId"
      :groups="groupedNodes"
      @saved="handleChanged"
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

.mgmt-group-unassigned {
  color: #64748b;
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

.mgmt-repo-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.5rem 0.25rem 1.4rem;
  font-size: 0.8rem;
  color: #64748b;
  cursor: pointer;
  border-radius: 6px;
}

.mgmt-repo-row:hover {
  background: rgba(14, 165, 233, 0.05);
  color: #0ea5e9;
}

.mgmt-repo-row.is-selected {
  background: rgba(14, 165, 233, 0.12);
  color: #0ea5e9;
  font-weight: 600;
}

.mgmt-repo-icon {
  width: 0.8rem;
  height: 0.8rem;
  flex-shrink: 0;
}

.mgmt-repo-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
