<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronRight, FileText, Layers } from '@/components/icons'
import { useRequirementSearch } from '@/composables/useRequirementSearch'
import type { RequirementOption } from '@/types/taskRail'

const props = defineProps<{ workspaceId: string; requirement: RequirementOption; selectedId?: string; lockedId?: string; disabled?: boolean; active: boolean }>()
const emit = defineEmits<{ select: [requirement: RequirementOption] }>()
const expanded = ref(false)
const hasChildren = computed(() => (props.requirement.child_count || 0) > 0)
const children = useRequirementSearch(() => props.workspaceId, () => props.active && expanded.value && hasChildren.value,
  () => ({ scope: 'children', parent_id: props.requirement.id }), { pageSize:8, append:false })
function activate() {
  if (hasChildren.value) expanded.value = !expanded.value
  else if (!props.disabled && props.requirement.can_link_task !== false && (!props.lockedId || props.lockedId === props.requirement.id)) emit('select', props.requirement)
}
</script>

<template>
  <div class="requirement-node">
    <button type="button" class="requirement-node-button" :class="{ selected: selectedId === requirement.id }"
      :disabled="!hasChildren && (disabled || requirement.can_link_task === false || Boolean(lockedId && lockedId !== requirement.id))"
      :aria-expanded="hasChildren ? expanded : undefined" :aria-pressed="hasChildren ? undefined : selectedId === requirement.id" @click="activate">
      <ChevronRight v-if="hasChildren" class="node-icon" :class="{ expanded }" /><FileText v-else class="node-icon" />
      <span v-if="!hasChildren" class="selection-indicator" :class="{ checked:selectedId === requirement.id }" />
      <span class="node-text"><strong>{{ requirement.title }}</strong><small v-if="requirement.parent_title">{{ requirement.parent_title }}</small></span>
      <span class="node-status" :class="{ draft:requirement.status === 'DRAFT' }">{{ requirement.status }}</span>
      <span v-if="hasChildren" class="child-count"><Layers class="node-icon" />{{ requirement.child_count }}</span>
    </button>
    <div v-if="hasChildren && expanded" class="requirement-children">
      <p v-if="children.loading.value">{{ $t('common.loading') }}</p>
      <button v-if="children.error.value" type="button" class="tree-action" @click="children.search()">{{ $t('task_rail.retry') }}</button>
      <RequirementPickerNode v-for="child in children.items.value" :key="child.id" :workspace-id="workspaceId" :requirement="child"
        :selected-id="selectedId" :locked-id="lockedId" :disabled="disabled" :active="active" @select="emit('select', $event)" />
      <div v-if="children.totalPages.value > 1" class="child-pagination">
        <button type="button" class="btn-secondary mini page-nav-btn" :disabled="children.page.value <= 1 || children.loading.value" @click="children.loadPage(children.page.value - 1)">{{ $t('skills.list.prev_page') }}</button>
        <span class="skills-page-info">{{ $t('skills.list.page_info', { page:children.page.value, total:children.totalPages.value }) }}</span>
        <button type="button" class="btn-secondary mini page-nav-btn" :disabled="children.page.value >= children.totalPages.value || children.loading.value" @click="children.loadPage(children.page.value + 1)">{{ $t('skills.list.next_page') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>
.child-pagination { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:8px 0; }
.requirement-node-button { display:flex; align-items:center; gap:8px; width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:10px; text-align:left; background:#fff; color:#334155; cursor:pointer; transition:border-color .2s,background .2s; }
.requirement-node-button:hover,.requirement-node-button.selected { background:#f0f9ff; border-color:#38bdf8; color:#0369a1; }
.selection-indicator { width:14px; height:14px; flex-shrink:0; border:1px solid #cbd5e1; border-radius:50%; background:#fff; }
.selection-indicator.checked { border:4px solid #0ea5e9; }
.node-status { padding:1px 6px; border-radius:999px; border:1px solid #bbf7d0; background:#dcfce7; color:#15803d; font-size:.65rem; font-weight:600; flex-shrink:0; }
.node-status.draft { color:#c2410c; background:#ffedd5; border-color:#fed7aa; }
.requirement-node-button:disabled { opacity:.55; cursor:default; }
.node-icon { width:15px; height:15px; flex-shrink:0; transition:transform .2s; }
.node-icon.expanded { transform:rotate(90deg); }
.node-text { display:flex; flex-direction:column; gap:3px; min-width:0; flex:1; }
.node-text strong { font-size:.8rem; font-weight:600; overflow-wrap:anywhere; }
.node-text small { color:#64748b; font-size:.7rem; }
.child-count { display:flex; align-items:center; gap:4px; color:#64748b; font-size:.72rem; }
.requirement-children { padding-left:15px; margin-left:17px; border-left:1px solid #e2e8f0; }
.requirement-children p,.tree-action { font-size:.75rem; color:#64748b; }
.tree-action { padding:8px; border:0; background:transparent; cursor:pointer; }
</style>
