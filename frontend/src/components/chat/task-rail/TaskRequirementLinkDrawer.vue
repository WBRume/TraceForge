<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import RequirementPickerSidebar from '@/components/task-create/RequirementPickerSidebar.vue'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import type { RequirementOption } from '@/types/taskRail'

const props = defineProps<{
  workspaceId: string
  taskId: string
  taskName: string
  requirements: RequirementOption[]
}>()
const emit = defineEmits<{ close: []; linked: [requirement: RequirementOption] }>()
const { t } = useI18n()
const assets = useWorkspaceAssets()
const selected = shallowRef<RequirementOption | null>(null)
const alreadyLinked = computed(() => props.requirements.some(item => item.id === selected.value?.id))

function close() {
  if (!assets.loading.value) emit('close')
}

async function save() {
  const requirement = selected.value
  if (!requirement || alreadyLinked.value || assets.loading.value) return
  const result = await assets.linkRequirementTask(props.workspaceId, requirement.id, {
    task_id: props.taskId,
    relation_type: 'RELATES_TO',
  })
  if (result) emit('linked', requirement)
}
</script>

<template>
  <Teleport to="body">
    <div class="requirement-link-overlay" @pointerdown.self="close">
      <section class="requirement-link-drawer" role="dialog" aria-modal="true" :aria-label="t('task_rail.link_requirement')">
        <header class="task-context"><strong :title="taskName">{{ taskName }}</strong><span>DONE</span></header>
        <RequirementPickerSidebar
          :workspace-id="workspaceId" :open="true" :selected="selected" :disabled="assets.loading.value"
          @select="selected = $event" @close="close"
        />
        <p v-if="assets.error.value" class="link-error" role="alert">{{ assets.error.value }}</p>
        <footer class="link-actions">
          <span class="selected-title" :title="selected?.title">{{ selected?.title }}</span>
          <button type="button" class="btn-secondary" :disabled="assets.loading.value" @click="close">{{ t('common.cancel') }}</button>
          <button type="button" class="btn-primary" :disabled="!selected || alreadyLinked || assets.loading.value" @click="save">
            {{ assets.loading.value ? t('common.loading') : alreadyLinked ? t('task_rail.selected_requirement') : t('common.save') }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.requirement-link-overlay { position:fixed; inset:0; z-index:1000; display:flex; justify-content:flex-end; background:rgba(15,23,42,.3); }
.requirement-link-drawer { display:flex; flex-direction:column; width:min(440px,100%); height:100%; background:#fff; box-shadow:-12px 0 32px rgba(15,23,42,.12); }
.task-context { display:flex; align-items:center; gap:12px; padding:18px 20px; border-bottom:1px solid #e2e8f0; }
.task-context strong { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.9rem; }
.task-context span { color:#047857; background:#d1fae5; padding:2px 8px; border-radius:999px; font-size:.7rem; }
.requirement-picker-sidebar.open { flex:1; min-height:0; width:100%; }
:deep(.sidebar-inner) { width:100%; box-shadow:none; }
.link-actions { display:flex; align-items:center; gap:8px; padding:16px 20px; border-top:1px solid #e2e8f0; }
.selected-title { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.8rem; color:#0369a1; }
.link-error { margin:0; padding:12px 20px; color:#dc2626; font-size:.8rem; }
</style>
