<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Boxes, Folder, Inbox, GitBranch, Plus, Pencil, Trash2 } from 'lucide-vue-next'
import type { OrgTreeNode } from '@/types/management'

const props = withDefaults(defineProps<{
  node: OrgTreeNode;
  canManage: boolean;
  selectedRepoId: string | null;
  depth: number;
}>(), {
  depth: 0,
})

const emit = defineEmits<{
  (e: 'select-repo', repoId: string): void;
  (e: 'add-child', node: OrgTreeNode): void;
  (e: 'edit-node', node: OrgTreeNode): void;
  (e: 'delete-node', node: OrgTreeNode): void;
}>()

const { t } = useI18n()

const isProductLine = computed(() => props.node.node_type === 'PRODUCT_LINE')
const isUnassigned = computed(() => props.node.node_type === 'UNASSIGNED')
const canAddChild = computed(() => props.canManage && isProductLine.value)

const indentStyle = computed(() => ({ paddingLeft: `${props.depth * 14}px` }))
</script>

<template>
  <div class="org-tree-row">
    <div class="org-node-header" :style="indentStyle">
      <span class="org-node-label" :class="{ 'is-unassigned': isUnassigned }">
        <Boxes v-if="isProductLine" class="org-node-icon" />
        <Folder v-else-if="!isUnassigned" class="org-node-icon" />
        <Inbox v-else class="org-node-icon" />
        <span class="org-node-name">{{ node.name }}</span>
      </span>
      <span v-if="canManage" class="org-node-actions">
        <button
          v-if="canAddChild"
          class="btn-ghost org-action-btn"
          :title="t('management.org.add_project_group')"
          @click.stop="emit('add-child', node)"
        >
          <Plus class="org-action-icon" />
        </button>
        <button
          class="btn-ghost org-action-btn"
          :title="t('management.org.edit_node')"
          @click.stop="emit('edit-node', node)"
        >
          <Pencil class="org-action-icon" />
        </button>
        <button
          class="btn-ghost org-action-btn org-action-danger"
          :title="t('management.org.delete_node')"
          @click.stop="emit('delete-node', node)"
        >
          <Trash2 class="org-action-icon" />
        </button>
      </span>
    </div>

    <div v-if="node.repositories && node.repositories.length" class="org-node-repos">
      <button
        v-for="repo in node.repositories"
        :key="repo.id"
        class="org-repo-item"
        :class="{ 'is-selected': repo.id === selectedRepoId }"
        @click.stop="emit('select-repo', repo.id)"
      >
        <GitBranch class="org-repo-icon" />
        <span class="org-repo-name">{{ repo.name }}</span>
      </button>
    </div>

    <div v-if="node.children && node.children.length" class="org-node-children">
      <OrgTreeNodeRow
        v-for="child in node.children"
        :key="child.id ?? ('unassigned-' + child.name)"
        :node="child"
        :can-manage="canManage"
        :selected-repo-id="selectedRepoId"
        :depth="depth + 1"
        @select-repo="emit('select-repo', $event)"
        @add-child="emit('add-child', $event)"
        @edit-node="emit('edit-node', $event)"
        @delete-node="emit('delete-node', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.org-tree-row {
  display: flex;
  flex-direction: column;
}

.org-node-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.4rem 0.5rem;
  border-radius: 8px;
  transition: background 0.2s;
}

.org-node-header:hover {
  background: rgba(14, 165, 233, 0.06);
}

.org-node-label {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: #334155;
}

.org-node-label.is-unassigned {
  color: #94a3b8;
  font-weight: 500;
}

.org-node-icon {
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  color: #64748b;
}

.org-node-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.org-node-actions {
  display: flex;
  align-items: center;
  gap: 0.2rem;
  opacity: 0;
  transition: opacity 0.15s;
}

.org-node-header:hover .org-node-actions {
  opacity: 1;
}

.org-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.2rem;
  border-radius: 6px;
}

.org-action-icon {
  width: 0.85rem;
  height: 0.85rem;
}

.org-action-danger:hover {
  color: #ef4444;
}

.org-node-repos {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.15rem 0 0.15rem 2rem;
}

.org-repo-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.28rem 0.5rem;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 0.82rem;
  color: #64748b;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}

.org-repo-item:hover {
  background: rgba(14, 165, 233, 0.08);
  color: #0ea5e9;
}

.org-repo-item.is-selected {
  background: rgba(14, 165, 233, 0.12);
  color: #0ea5e9;
  font-weight: 600;
}

.org-repo-icon {
  width: 0.8rem;
  height: 0.8rem;
  flex-shrink: 0;
}

.org-repo-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.org-node-children {
  display: flex;
  flex-direction: column;
}
</style>

<style scoped src="@/styles/management/management-shared.css"></style>