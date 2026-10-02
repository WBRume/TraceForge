<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Layers, Star, Zap, Search } from '@/components/icons'
import { useTaskRailStore } from '@/stores/taskRail'
import { requirementLabel, requirementMark, type RequirementOption } from '@/types/taskRail'
import RequirementSearchPopover from './RequirementSearchPopover.vue'

defineProps<{ workspaceId: string; collapsed: boolean }>()
const rail = useTaskRailStore()
const visibleSlots = computed(() => rail.slots.filter((item): item is RequirementOption => Boolean(item)))
const { t } = useI18n()
const searchOpen = ref(false)
const anchor = ref({ left: 80, top: 100 })
const moreButton = useTemplateRef<HTMLButtonElement>('moreButton')
onMounted(() => { void rail.loadSlots().catch(() => undefined) })
function openSearch() {
  const rect = moreButton.value?.getBoundingClientRect()
  if (rect) anchor.value = { left: rect.right + 12, top: rect.top - 120 }
  searchOpen.value = true
}
async function closeSearch() { searchOpen.value = false; await nextTick(); moreButton.value?.focus() }
function select(requirement: RequirementOption) { rail.selectRequirement(requirement); void closeSearch() }
</script>

<template>
  <div class="task-host-rail" :class="{ compact: collapsed }" role="group" :aria-label="t('task_rail.views')">
    <button v-for="item in [{ view: 'all' as const, icon: Layers }, { view: 'following' as const, icon: Star }, { view: 'independent' as const, icon: Zap }]" :key="item.view"
      type="button" class="rail-button" :class="{ active: rail.view === item.view }" :title="t(`task_rail.${item.view}`)" :aria-label="t(`task_rail.${item.view}`)" :aria-pressed="rail.view === item.view" @click="rail.selectView(item.view)">
      <component :is="item.icon" class="rail-icon" /><span v-if="!collapsed" class="rail-label">{{ t(`task_rail.${item.view}`) }}</span>
    </button>
    <button v-for="requirement in visibleSlots" :key="requirement.id" type="button" class="rail-button requirement-slot"
      :class="{ active: rail.selectedRequirement?.id === requirement.id }" :title="requirement.title"
      :aria-label="requirementLabel(requirement)" :aria-pressed="rail.selectedRequirement?.id === requirement.id" @click="rail.selectRequirement(requirement)">
      <span class="requirement-mark">{{ requirementMark(requirement) }}</span><span v-if="!collapsed" class="rail-label">{{ requirementLabel(requirement) }}</span>
    </button>
    <button ref="moreButton" type="button" class="rail-button" :title="t('task_rail.more')" :aria-label="t('task_rail.more')" :aria-expanded="searchOpen" @click="openSearch"><Search class="rail-icon" /><span v-if="!collapsed" class="rail-label">{{ t('task_rail.more') }}</span></button>
    <RequirementSearchPopover v-if="searchOpen" :workspace-id="workspaceId" :pinned-ids="rail.pinnedIds" :anchor="anchor" @close="closeSearch" @select="select" @pin="rail.togglePin" />
  </div>
</template>

<style scoped>
.task-host-rail { display:flex; flex-direction:column; gap:4px; padding:6px 8px 10px; max-height:212px; box-sizing:content-box; flex-shrink:0; }
.rail-button { display:flex; align-items:center; gap:10px; height:32px; min-height:32px; width:100%; padding:0 8px; border:0; border-radius:8px; background:transparent; color:var(--color-text-muted); cursor:pointer; transition:background .15s, color .15s; }
.rail-button:hover { color:var(--color-primary-600); background:var(--color-primary-50); }
.rail-button.active { color:var(--color-primary-600); background:var(--color-primary-100); box-shadow:inset 0 0 0 1px rgba(14,165,233,.16); }
.rail-button:focus-visible { outline:2px solid var(--color-primary-500); outline-offset:2px; }
.rail-button:disabled { opacity:.4; cursor:default; }
.rail-icon { width:16px; height:16px; flex-shrink:0; }
.rail-label { font-size:.75rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.requirement-mark { display:inline-flex; width:16px; justify-content:center; flex-shrink:0; font-size:.62rem; font-weight:600; }
.compact { padding-inline:8px; align-items:center; }
.compact .rail-button { width:32px; padding:0; justify-content:center; }
.compact .requirement-mark { width:30px; }
</style>
