<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { requirementLabel, type RequirementOption } from '@/types/taskRail'
defineProps<{ workspaceId: string; taskId?: string; requirements: RequirementOption[] }>()
</script>

<template>
  <span class="task-requirement-badges">
    <RouterLink v-for="requirement in requirements" :key="requirement.id" class="requirement-badge"
      :title="`${requirement.title} · ${requirement.status}`" :to="{ name:'workspaceAssetsRequirementDetail', params:{ wsId:workspaceId, requirementId:requirement.id }, query:{ from:'session', taskId } }" @click.stop>
      <span aria-hidden="true">#</span><span class="badge-label">{{ requirementLabel(requirement) }}</span>
    </RouterLink>
  </span>
</template>

<style scoped>
.task-requirement-badges { display:flex; flex-wrap:wrap; gap:4px; min-width:0; }
.requirement-badge { display:inline-flex; align-items:center; gap:4px; max-width:min(100%,220px); padding:2px 6px; border-radius:5px; color:var(--color-primary-600); background:var(--color-primary-50); text-decoration:none; font-size:.7rem; }
.badge-label { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.requirement-badge:hover { background:var(--color-primary-100); }
</style>
