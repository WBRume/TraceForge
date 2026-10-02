<script setup lang="ts">
import { FileText, Search } from '@/components/icons'
import { useRequirementSearch } from '@/composables/useRequirementSearch'
import type { RequirementOption } from '@/types/taskRail'
import SidebarPanel from './SidebarPanel.vue'
import RequirementPickerNode from './RequirementPickerNode.vue'

const props = defineProps<{ workspaceId: string; open: boolean; selected: RequirementOption | null; lockedId?: string; disabled?: boolean; initialParent?: RequirementOption | null }>()
const emit = defineEmits<{ close: []; select: [requirement: RequirementOption | null] }>()
const search = useRequirementSearch(() => props.workspaceId, () => props.open, (query) => ({
  scope: props.initialParent ? 'children' : query.trim() ? 'all' : 'roots',
  parent_id: props.initialParent?.id,
}))
</script>

<template>
  <SidebarPanel class="requirement-picker-sidebar" :inert="!open" :aria-hidden="!open" :open="open" :badge="selected ? $t('task_rail.selected_requirement') : $t('task_rail.optional')" :badge-active="Boolean(selected)" :subtitle="$t('task_rail.leaf_only')" @close="emit('close')">
    <template #title><div class="skills-sidebar-title"><FileText class="w-4 h-4 text-primary" /><h3>{{ $t('task_rail.requirement_optional') }}</h3></div></template>
    <template #tools><div class="skills-search-wrapper"><Search class="w-4 h-4 skills-search-icon" />
      <input v-model="search.query.value" class="skills-search-input" :placeholder="$t('task_rail.search')" :aria-label="$t('task_rail.search')" />
    </div></template>
    <template #filters><div class="skills-filter-row"><span v-if="initialParent" class="parent-context">{{ initialParent.title }}</span>
      <button v-if="selected && !lockedId" type="button" class="tool-text-btn" :disabled="disabled" @click="emit('select', null)">{{ $t('task_rail.clear_requirement') }}</button>
      <span v-if="lockedId" class="parent-context">{{ $t('task_rail.inherited') }}</span>
    </div></template>
    <div v-if="search.error.value" class="skills-state center"><button type="button" class="tool-text-btn" @click="search.search()">{{ $t('task_rail.retry') }}</button></div>
    <p v-if="search.loading.value" class="skills-state center">{{ $t('common.loading') }}</p>
    <p v-else-if="!search.items.value.length && !search.error.value" class="skills-state center">{{ $t('task_rail.no_requirements') }}</p>
    <RequirementPickerNode v-for="item in search.items.value" :key="item.id" :workspace-id="workspaceId" :requirement="item" :selected-id="selected?.id" :locked-id="lockedId" :disabled="disabled" :active="open" @select="emit('select', $event)" />
    <template v-if="search.items.value.length < search.total.value" #footer><button type="button" class="tool-text-btn" :disabled="search.loading.value" @click="search.search(false)">{{ $t('task_rail.load_more') }}</button></template>
  </SidebarPanel>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>.parent-context { color:#64748b; font-size:.72rem; overflow-wrap:anywhere; }</style>
