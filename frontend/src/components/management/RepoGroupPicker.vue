<!-- Repository group tree picker: checking a group selects all repositories
     inside it. Emits the selected repository ids. The tree renders every
     level recursively; the dialog is teleported to <body> so it covers the
     whole page instead of being confined to the parent card. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import RepoGroupPickerNode from '@/components/management/RepoGroupPickerNode.vue'
import { getRepoGroupTree } from '@/services/managementApi'
import type { RepoGroupRepo, RepoGroupTreeNode } from '@/types/management'

const props = withDefaults(defineProps<{
  show: boolean
  excludeIds?: string[]
  modelValue: string[]
  allowedRepoTypes?: string[]
}>(), {
  excludeIds: () => [],
  allowedRepoTypes: () => [],
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
  (e: 'close'): void
  (e: 'confirm'): void
}>()

const tree = ref<RepoGroupTreeNode[]>([])
const loading = ref(false)
const keyword = ref('')

const load = async () => {
  loading.value = true
  try {
    const res = await getRepoGroupTree()
    tree.value = res.items || []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (visible) => {
    if (visible) {
      keyword.value = ''
      void load()
    }
  },
  { immediate: true },
)

// 只保留含允许类型仓库的组（直接或子孙有允许仓库），空组不展示
const repoAllowed = (repo: RepoGroupRepo): boolean => {
  if (!props.allowedRepoTypes || props.allowedRepoTypes.length === 0) return true
  return props.allowedRepoTypes.includes(repo.repo_type)
}

const hasAllowedRepos = (node: RepoGroupTreeNode): boolean => {
  if ((node.repositories || []).some(repoAllowed)) return true
  return (node.children || []).some(hasAllowedRepos)
}

// 搜索过滤：仅按仓库组名称匹配；命中的组展示整棵子树，
// 未命中的祖先组仅作为路径保留（不展示其直属仓库）。
const filteredTree = computed<RepoGroupTreeNode[]>(() => {
  const kw = keyword.value.trim().toLowerCase()
  const matchText = (text: string): boolean =>
    String(text || '').toLowerCase().includes(kw)
  const filterNode = (node: RepoGroupTreeNode): RepoGroupTreeNode | null => {
    if (!hasAllowedRepos(node)) return null
    const repositories = (node.repositories || []).filter(repoAllowed)
    if (!kw) {
      const children: RepoGroupTreeNode[] = []
      for (const child of node.children || []) {
        const filtered = filterNode(child)
        if (filtered) children.push(filtered)
      }
      return { ...node, repositories, children }
    }
    if (matchText(node.name)) {
      return { ...node, repositories }
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
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="mgmt-modal-overlay"
      @pointerdown.self="emit('close')"
    >
      <section class="mgmt-modal group-picker-dialog" role="dialog" aria-modal="true">
        <header class="group-picker-header">
          <h3>{{ $t('management.product.select_repos_hint') }}</h3>
        </header>

        <div class="group-picker-toolbar">
          <div class="mgmt-search-wrap">
            <Search class="w-4 h-4 search-icon" />
            <input v-model="keyword" type="text" class="mgmt-search" :placeholder="$t('management.repo_group.search_placeholder')" />
          </div>
        </div>

        <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

        <div v-else-if="filteredTree.length === 0" class="mgmt-empty">
          {{ $t('management.common.empty') }}
        </div>

        <div v-else class="group-picker-tree">
          <RepoGroupPickerNode
            v-for="node in filteredTree"
            :key="node.id ?? node.name"
            :node="node"
            :depth="0"
            :exclude-ids="excludeIds ?? []"
            :model-value="modelValue"
            @update:model-value="emit('update:modelValue', $event)"
          />
        </div>

        <footer class="mgmt-modal-actions">
          <button type="button" class="btn-secondary" @click="emit('close')">
            {{ $t('common.cancel') }}
          </button>
          <button type="button" class="btn-primary" @click="emit('confirm')">
            {{ $t('common.confirm') }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.group-picker-dialog {
  max-width: 560px;
  display: flex;
  flex-direction: column;
  max-height: 88vh;
}

.group-picker-header h3 {
  font-size: 0.95rem;
}

.group-picker-toolbar {
  margin-bottom: 0.75rem;
}

.mgmt-search-wrap {
  position: relative;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
}

.mgmt-search-wrap .mgmt-search {
  width: 100%;
  padding-left: 2rem;
}

.group-picker-tree {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  overflow-y: auto;
  flex: 1;
  min-height: 120px;
  padding: 0.25rem;
}
</style>
