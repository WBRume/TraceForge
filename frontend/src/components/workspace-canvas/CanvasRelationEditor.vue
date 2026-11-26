<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight } from '@/components/icons'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { RequirementTaskRelation } from '@/types/workspaceAssets'
import type { CanvasRelation } from './model'

const props = defineProps<{ link: CanvasRelation; requirement: string; task: string; saving: boolean; pendingAcceptance: boolean }>()
const emit = defineEmits<{ close: []; update: [type: RequirementTaskRelation]; unlink: [] }>()
const { t } = useI18n()
const draft = shallowRef<RequirementTaskRelation>('RELATES_TO')
const options = computed(() => [
  { value: 'COVERS', label: t('workspace_assets.requirements.relation_types.covers_short') },
  { value: 'RELATES_TO', label: t('workspace_assets.requirements.relation_types.relates_to_short') },
])
const confirm = shallowRef<'unlink' | 'update' | null>(null)
watch(() => props.link.relation_type, value => { draft.value = value === 'COVERS' ? value : 'RELATES_TO' }, { immediate: true })
const confirmMessage = computed(() => {
  const prompt = confirm.value === 'unlink' ? t('workspace_canvas.actions.unlink_prompt')
    : t('workspace_assets.requirements.task_links.change_relation_confirm', { name: props.task })
  return props.pendingAcceptance && (confirm.value === 'update' || props.link.relation_type === 'COVERS')
    ? `${prompt} ${t('workspace_assets.requirements.task_links.review_scope_changed')}` : prompt
})

function submit() {
  if (props.pendingAcceptance) confirm.value = 'update'
  else emit('update', draft.value)
}

function accept() {
  if (confirm.value === 'unlink') emit('unlink')
  else if (confirm.value === 'update') emit('update', draft.value)
  confirm.value = null
}
</script>

<template>
  <el-dialog :model-value="true" class="canvas-dialog" :title="t('workspace_canvas.actions.edit_relation')" width="min(530px, 95vw)"
    append-to-body :close-on-click-modal="false" :close-on-press-escape="!saving && !confirm" :show-close="!saving" @close="emit('close')">
    <div class="canvas-relation-editor">
      <div class="directions">
        <span><small>{{ t('workspace_canvas.kind.task') }}</small><strong>{{ task }}</strong></span>
        <ArrowRight :size="17" />
        <span><small>{{ t('workspace_canvas.kind.requirement') }}</small><strong>{{ requirement }}</strong></span>
      </div>
      <BaseSelect v-model="draft" :options="options" :disabled="saving" :aria-label="t('workspace_canvas.actions.relation_type')" />
    </div>
    <template #footer>
      <el-button type="danger" plain :disabled="saving" @click="confirm = 'unlink'">{{ t('workspace_canvas.actions.unlink') }}</el-button>
      <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :disabled="draft === link.relation_type" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
  <ConfirmActionModal :show="Boolean(confirm)" :title="t(confirm === 'unlink' ? 'workspace_canvas.actions.unlink' : 'workspace_canvas.actions.edit_relation')"
    :message="confirmMessage" :cancel-text="t('common.cancel')" :confirm-text="t('common.confirm')"
    :tone="confirm === 'unlink' ? 'danger' : 'primary'" @cancel="confirm = null" @confirm="accept" />
</template>

<style scoped>
.canvas-relation-editor { display: grid; gap: 12px; }
.directions { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.directions > span { flex: 1; min-width: 0; overflow-wrap: anywhere; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; }
.directions small { display: block; margin-bottom: 3px; color: #64748b; }
.directions strong { font-weight: 550; }
</style>
