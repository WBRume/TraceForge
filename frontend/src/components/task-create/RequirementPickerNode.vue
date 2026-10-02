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
  () => ({ scope: 'children', parent_id: props.requirement.id }))
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
      <span class="node-text"><strong>{{ requirement.title }}</strong><small v-if="requirement.parent_title">{{ requirement.parent_title }}</small><small>{{ requirement.status }}</small></span>
      <span v-if="hasChildren" class="child-count"><Layers class="node-icon" />{{ requirement.child_count }}</span>
    </button>
    <div v-if="hasChildren && expanded" class="requirement-children">
      <p v-if="children.loading.value">{{ $t('common.loading') }}</p>
      <button v-if="children.error.value" type="button" class="tree-action" @click="children.search()">{{ $t('task_rail.retry') }}</button>
      <RequirementPickerNode v-for="child in children.items.value" :key="child.id" :workspace-id="workspaceId" :requirement="child"
        :selected-id="selectedId" :locked-id="lockedId" :disabled="disabled" :active="active" @select="emit('select', $event)" />
      <button v-if="children.items.value.length < children.total.value" type="button" class="tree-action" :disabled="children.loading.value" @click="children.search(false)">{{ $t('task_rail.load_more') }}</button>
    </div>
  </div>
</template>

<style scoped>
.requirement-node-button { display:flex; align-items:center; gap:8px; width:100%; padding:10px; border:0; border-radius:8px; text-align:left; background:transparent; color:#334155; cursor:pointer; }
.requirement-node-button:hover,.requirement-node-button.selected { background:#e0f2fe; color:#0369a1; }
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
