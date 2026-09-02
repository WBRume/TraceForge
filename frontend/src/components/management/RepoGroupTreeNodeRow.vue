<script setup lang="ts">
import { Folder, Pencil, Trash2 } from 'lucide-vue-next'
import IconActionButton from '@/components/management/IconActionButton.vue'
import type { RepoGroupTreeNode } from '@/types/management'

defineProps<{
  node: RepoGroupTreeNode;
  canManage: boolean;
  selectedGroupId: string | null;
  depth: number;
}>()

const emit = defineEmits<{
  (e: 'select-group', groupId: string | null): void;
  (e: 'add-child', groupId: string): void;
  (e: 'edit-group', group: { id: string; name: string; parent_id: string | null }): void;
  (e: 'delete-group', group: { id: string; name: string; parent_id: string | null }): void;
  (e: 'changed'): void;
}>()
</script>

<template>
  <div class="mgmt-group-node">
    <div
      class="mgmt-group-row"
      :class="{ 'is-selected': node.id !== null && node.id === selectedGroupId }"
      @click="emit('select-group', node.id)"
    >
      <Folder class="mgmt-group-icon" />
      <span class="mgmt-group-name">{{ node.name }}</span>
      <span v-if="canManage" class="mgmt-group-actions">
        <IconActionButton
          :icon="Pencil"
          :title="$t('management.repo_group.edit')"
          @click="emit('edit-group', { id: node.id!, name: node.name, parent_id: node.parent_id })"
        />
        <IconActionButton
          :icon="Trash2"
          :title="$t('management.repo_group.delete')"
          tone="danger"
          @click="emit('delete-group', { id: node.id!, name: node.name, parent_id: node.parent_id })"
        />
      </span>
    </div>

    <div class="mgmt-group-children">
      <RepoGroupTreeNodeRow
        v-for="child in node.children"
        :key="child.id ?? child.name"
        :node="child"
        :can-manage="canManage"
        :selected-group-id="selectedGroupId"
        :depth="depth + 1"
        @select-group="emit('select-group', $event)"
        @add-child="emit('add-child', $event)"
        @edit-group="emit('edit-group', $event)"
        @delete-group="emit('delete-group', $event)"
        @changed="emit('changed')"
      />
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.mgmt-group-node {
  display: flex;
  flex-direction: column;
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

.mgmt-group-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  opacity: 0;
  transition: opacity 0.15s;
}

.mgmt-group-row:hover .mgmt-group-actions {
  opacity: 1;
}

.mgmt-group-children {
  margin-left: 1rem;
  padding-left: 0.5rem;
  border-left: 1px solid #e2e8f0;
}
</style>
