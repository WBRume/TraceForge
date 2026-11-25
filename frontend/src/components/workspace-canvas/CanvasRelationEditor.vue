<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, X } from '@/components/icons'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { RequirementTaskRelation } from '@/types/workspaceAssets'
import type { CanvasRelation } from './model'

const props = defineProps<{ link: CanvasRelation; requirement: string; task: string; saving: boolean; pendingAcceptance: boolean }>()
const emit = defineEmits<{ close: []; update: [type: RequirementTaskRelation]; unlink: [] }>()
const { t } = useI18n()
const draft = shallowRef<RequirementTaskRelation>('RELATES_TO')
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
  <form class="canvas-relation-editor" :aria-label="t('workspace_canvas.actions.edit_relation')"
    @keydown.esc.stop.prevent="emit('close')" @submit.prevent="submit">
    <header>
      <h2>{{ t('workspace_canvas.actions.edit_relation') }}</h2>
      <button class="close-relation" type="button" :disabled="saving" :aria-label="t('common.close')" @click="emit('close')"><X :size="17" /></button>
    </header>
    <div class="directions">
      <span><small>{{ t('workspace_canvas.kind.task') }}</small><strong>{{ task }}</strong></span>
      <ArrowRight :size="17" />
      <span><small>{{ t('workspace_canvas.kind.requirement') }}</small><strong>{{ requirement }}</strong></span>
    </div>
    <el-select v-model="draft" :disabled="saving" :aria-label="t('workspace_canvas.actions.relation_type')">
      <el-option value="COVERS" :label="t('workspace_assets.requirements.relation_types.covers_short')" />
      <el-option value="RELATES_TO" :label="t('workspace_assets.requirements.relation_types.relates_to_short')" />
    </el-select>
    <footer>
      <el-button type="danger" plain :disabled="saving" @click="confirm = 'unlink'">{{ t('workspace_canvas.actions.unlink') }}</el-button>
      <el-button type="primary" native-type="submit" :disabled="draft === link.relation_type" :loading="saving">{{ t('common.save') }}</el-button>
    </footer>
  </form>
  <ConfirmActionModal :show="Boolean(confirm)" :title="t(confirm === 'unlink' ? 'workspace_canvas.actions.unlink' : 'workspace_canvas.actions.edit_relation')"
    :message="confirmMessage" :cancel-text="t('common.cancel')" :confirm-text="t('common.confirm')"
    :tone="confirm === 'unlink' ? 'danger' : 'primary'" @cancel="confirm = null" @confirm="accept" />
</template>

<style scoped>
.canvas-relation-editor { position: absolute; z-index: 8; inset: 67px 16px auto auto; width: min(360px, calc(100% - 80px)); display: grid; gap: 12px; padding: 15px; border: 1px solid var(--canvas-line); border-radius: 12px; background: var(--canvas-chrome); box-shadow: 0 12px 32px #25345928; }
header, footer { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
h2 { margin: 0; font-size: 15px; }
.close-relation { display: grid; place-items: center; border: 0; border-radius: 7px; padding: 5px; background: transparent; color: var(--canvas-muted); cursor: pointer; }
.close-relation:hover { background: var(--canvas-hover); }
.directions { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.directions > span { flex: 1; min-width: 0; overflow-wrap: anywhere; border: 1px solid var(--canvas-line); border-radius: 7px; padding: 7px; }
.directions small { display: block; margin-bottom: 3px; color: var(--canvas-muted); }
.directions strong { font-weight: 550; }
</style>
