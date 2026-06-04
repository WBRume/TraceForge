<script setup lang="ts">
import { computed, proxyRefs, type Component } from 'vue'
import { FilePlus2, FolderPlus, Trash2, Edit3, FolderTree } from 'lucide-vue-next'
import type { SkillEditorViewModel, SkillFileNode } from '@/composables/useSkillEditorViewModel'
import { resolveSkillTreeVisual } from '@/utils/skillFileTreeVisual'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const rawVm = props.vm
const vm = proxyRefs(rawVm)

type FlatNode = {
  path: string
  name: string
  node_type: 'file' | 'directory'
  depth: number
  tone: string
  extLabel: string
  icon: Component
}

const flattenNodes = (nodes: SkillFileNode[], depth = 0): FlatNode[] => {
  const result: FlatNode[] = []
  nodes.forEach((node) => {
    const visual = resolveSkillTreeVisual(node.name, node.node_type)
    result.push({
      path: node.path,
      name: node.name,
      node_type: node.node_type,
      depth,
      tone: visual.tone,
      extLabel: visual.extLabel,
      icon: visual.icon,
    })
    if (node.node_type === 'directory' && node.children?.length) {
      result.push(...flattenNodes(node.children, depth + 1))
    }
  })
  return result
}

const flatNodes = computed(() => flattenNodes(vm.fileTree || []))
</script>

<template>
  <section class="file-tree-panel glass-panel">
    <div class="file-tree-header">
      <div class="file-tree-title">
        <FolderTree class="w-4 h-4" />
        <span>{{ $t('skills.editor.file_tree') }}</span>
      </div>
      <div v-if="!vm.isReadOnly" class="file-tree-actions">
        <button class="icon-btn-ghost" :title="$t('skills.editor.new_file')" @click="vm.createNode('file')">
          <FilePlus2 class="w-4 h-4" />
        </button>
        <button class="icon-btn-ghost" :title="$t('skills.editor.new_folder')" @click="vm.createNode('directory')">
          <FolderPlus class="w-4 h-4" />
        </button>
        <button class="icon-btn-ghost" :title="$t('skills.editor.rename_file')" :disabled="!vm.canOperateSelectedNode" @click="vm.openRenameNodeDialog">
          <Edit3 class="w-4 h-4" />
        </button>
        <button class="icon-btn-ghost danger" :title="$t('skills.editor.delete_file')" :disabled="!vm.canOperateSelectedNode" @click="vm.openDeleteNodeConfirm">
          <Trash2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <div v-if="vm.treeLoading" class="tree-state">{{ $t('skills.editor.loading') }}</div>
    <div v-else-if="flatNodes.length === 0" class="tree-state">{{ $t('skills.editor.file_tree_empty') }}</div>

    <div v-else class="file-tree-list custom-scrollbar">
      <button
        v-for="node in flatNodes"
        :key="node.path"
        class="tree-row"
        :class="{ active: node.path === vm.selectedTreePath, directory: node.node_type === 'directory' }"
        :style="{ paddingLeft: `${0.85 + node.depth * 0.9}rem` }"
        :title="node.path"
        @click="vm.selectTreeNode(node.path, node.node_type)"
      >
        <span class="tree-row-icon-shell" :class="`tree-tone-${node.tone}`">
          <component :is="node.icon" class="tree-row-icon" />
        </span>
        <span class="tree-row-name">{{ node.name }}</span>
        <span v-if="node.node_type === 'file'" class="tree-row-ext" :class="`tree-tone-${node.tone}`">
          {{ node.extLabel }}
        </span>
      </button>
    </div>
  </section>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
