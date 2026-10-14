<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import CollaborationRepositories from './CollaborationRepositories.vue'
import type { RepositoryUpdates } from '@/composables/collaboration/useRepositoryUpdates'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'

const props = withDefaults(defineProps<{ model: RepositoryUpdates; controller?: LocalCollaboration; setup?: boolean }>(), { setup:true })
const emit = defineEmits<{ device: [] }>()
const m = computed(() => proxyRefs(props.model))
</script>

<template>
  <section class="repository-update">
    <header class="update-heading">
      <div><h3>任务仓库 <span>{{ m.summary?.repositories.length || 0 }} 个仓库</span></h3><p>云端版本与本地仓库映射</p></div>
    </header>
    <div class="repository-overview">
      <CollaborationRepositories :controller="controller" :setup="setup" embedded :versions="m.summary?.repositories" @device="emit('device')" />
    </div>
  </section>
</template>

<style scoped>
.repository-update { display:flex; flex-direction:column; flex:1; min-height:0; min-width:0; }
.update-heading { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; padding:16px 20px; border-bottom:1px solid #e2e8f0; }
h3 { margin:0; font-size:14px; color:#0f172a; } h3 span { margin-left:6px; padding:2px 7px; border-radius:12px; background:#f1f5f9; color:#64748b; font-size:10px; font-weight:400; }
p { margin:4px 0 0; font-size:11px; color:#64748b; }
.repository-overview { flex:1; min-height:0; overflow:auto; padding:0 20px 20px; }
</style>
