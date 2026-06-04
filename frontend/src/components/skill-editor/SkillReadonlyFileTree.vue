<script setup lang="ts">
import { computed, type Component } from 'vue'
import { FolderTree } from 'lucide-vue-next'
import type { SkillFileNode } from '@/composables/useSkillEditorViewModel'
import { resolveSkillTreeVisual } from '@/utils/skillFileTreeVisual'

const props = defineProps<{
  nodes: SkillFileNode[]
  activePath: string
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'select', path: string): void
}>()

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

const flatNodes = computed(() => flattenNodes(props.nodes || []))

const onSelect = (node: FlatNode) => {
  if (node.node_type === 'file') {
    emit('select', node.path)
  }
}
</script>

<template>
  <section class="file-tree-panel glass-panel">
    <div class="file-tree-header">
      <div class="file-tree-title">
        <FolderTree class="w-4 h-4" />
        <span>{{ $t('skills.editor.historical_files') }}</span>
      </div>
    </div>

    <div v-if="loading" class="tree-state">{{ $t('skills.editor.loading') }}</div>
    <div v-else-if="flatNodes.length === 0" class="tree-state">{{ $t('skills.editor.file_tree_empty') }}</div>

    <div v-else class="file-tree-list custom-scrollbar">
      <button
        v-for="node in flatNodes"
        :key="node.path"
        class="tree-row"
        :class="{ active: node.path === activePath, directory: node.node_type === 'directory' }"
        :style="{ paddingLeft: `${0.85 + node.depth * 0.9}rem` }"
        :title="node.path"
        @click="onSelect(node)"
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
