<script setup lang="ts">
import { FileText, Loader2, RefreshCw, Search, X } from '@/components/icons'
import { useRequirementSearch } from '@/composables/useRequirementSearch'
import type { RequirementOption } from '@/types/taskRail'
import SidebarPanel from './SidebarPanel.vue'
import RequirementPickerNode from './RequirementPickerNode.vue'

const props = defineProps<{ workspaceId: string; open: boolean; selected: RequirementOption | null; lockedId?: string; disabled?: boolean; initialParent?: RequirementOption | null }>()
const emit = defineEmits<{ close: []; select: [requirement: RequirementOption | null] }>()
const search = useRequirementSearch(() => props.workspaceId, () => props.open, (query) => ({
  scope: props.initialParent ? 'children' : query.trim() ? 'all' : 'roots',
  parent_id: props.initialParent?.id,
}), { pageSize:8, append:false })
</script>

<template>
  <SidebarPanel class="requirement-picker-sidebar" :inert="!open" :aria-hidden="!open" :open="open" :badge="selected ? $t('task_rail.selected_requirement') : $t('task_rail.optional')" :badge-active="Boolean(selected)" :subtitle="$t('task_rail.leaf_only')" @close="emit('close')">
    <template #title><div class="skills-sidebar-title"><FileText class="w-4 h-4 text-primary" /><h3>{{ $t('task_rail.requirement_optional') }}</h3></div></template>
    <template #tools><div class="skills-sidebar-tools"><div class="skills-search-wrapper"><Search class="w-4 h-4 skills-search-icon" />
      <input v-model="search.query.value" type="text" class="skills-search-input" :placeholder="$t('task_rail.search')" :aria-label="$t('task_rail.search')" />
      <button v-if="search.query.value" type="button" class="skills-search-clear" :aria-label="$t('task_rail.clear_search')" @click="search.query.value = ''"><X class="w-3.5 h-3.5" /></button>
    </div><button type="button" class="tool-icon-btn" :title="$t('skills.task_panel.refresh')" :disabled="search.loading.value" @click="search.loadPage()"><RefreshCw class="w-3.5 h-3.5" :class="{ spin:search.loading.value }" /></button></div></template>
    <template #filters><div class="skills-filter-row"><span v-if="initialParent" class="parent-context">{{ initialParent.title }}</span>
      <button v-if="selected && !lockedId" type="button" class="tool-text-btn" :disabled="disabled" @click="emit('select', null)">{{ $t('task_rail.clear_requirement') }}</button>
      <span v-if="lockedId" class="parent-context">{{ $t('task_rail.inherited') }}</span>
    </div></template>
    <div v-if="search.error.value" class="skills-state center"><button type="button" class="tool-text-btn" @click="search.search()">{{ $t('task_rail.retry') }}</button></div>
    <div v-if="search.loading.value" class="skills-state center"><Loader2 class="w-6 h-6 spin text-primary" /><span>{{ $t('common.loading') }}</span></div>
    <p v-else-if="!search.items.value.length && !search.error.value" class="skills-state center">{{ $t('task_rail.no_requirements') }}</p>
    <div v-else class="skills-list"><RequirementPickerNode v-for="item in search.items.value" :key="item.id" :workspace-id="workspaceId" :requirement="item" :selected-id="selected?.id" :locked-id="lockedId" :disabled="disabled" :active="open" @select="emit('select', $event)" /></div>
    <template #footer>
      <button type="button" class="btn-secondary mini page-nav-btn" :disabled="search.page.value <= 1 || search.loading.value" @click="search.loadPage(search.page.value - 1)">{{ $t('skills.list.prev_page') }}</button>
      <div class="pagination-info"><span class="skills-page-info">{{ $t('skills.list.page_info', { page:search.page.value, total:search.totalPages.value }) }}</span><span class="pagination-badge">{{ search.total.value }}</span></div>
      <button type="button" class="btn-secondary mini page-nav-btn" :disabled="search.page.value >= search.totalPages.value || search.loading.value" @click="search.loadPage(search.page.value + 1)">{{ $t('skills.list.next_page') }}</button>
    </template>
  </SidebarPanel>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>
.parent-context { color:#64748b; font-size:.72rem; overflow-wrap:anywhere; }
.skills-list { display:flex; flex-direction:column; gap:6px; }
</style>
