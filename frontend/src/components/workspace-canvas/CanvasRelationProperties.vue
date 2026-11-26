<script setup lang="ts">
import { shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight } from '@/components/icons'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { CanvasGraphRelation } from './model'

const props = defineProps<{
  link: CanvasGraphRelation
  sourceTitle: string
  targetTitle: string
  canDetach: boolean
  saving: boolean
}>()
const emit = defineEmits<{ close: []; detach: [] }>()
const { t } = useI18n()
const confirm = shallowRef(false)

function detach() {
  confirm.value = false
  if (props.canDetach && !props.saving) emit('detach')
}
</script>

<template>
  <el-dialog :model-value="true" :title="t(`workspace_canvas.relations.${link.relation_type}`)" width="min(530px, 95vw)"
    append-to-body :close-on-click-modal="false" :close-on-press-escape="!saving && !confirm" :show-close="!saving" @close="emit('close')">
    <div class="directions">
      <span><small>{{ t(`workspace_canvas.kind.${link.source.kind}`) }}</small><strong>{{ sourceTitle }}</strong></span>
      <ArrowRight :size="17" />
      <span><small>{{ t(`workspace_canvas.kind.${link.target.kind}`) }}</small><strong>{{ targetTitle }}</strong></span>
    </div>
    <template #footer>
      <el-button v-if="canDetach" type="danger" plain :disabled="saving" @click="confirm = true">
        {{ t('workspace_canvas.actions.unlink') }}
      </el-button>
      <el-button :disabled="saving" @click="emit('close')">{{ t('common.close') }}</el-button>
    </template>
  </el-dialog>
  <ConfirmActionModal :show="confirm" :title="t('workspace_canvas.actions.unlink')"
    :message="t('workspace_canvas.actions.detach_document_prompt')" :cancel-text="t('common.cancel')"
    :confirm-text="t('common.confirm')" tone="danger" @cancel="confirm = false" @confirm="detach" />
</template>

<style scoped>
.directions { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.directions > span { flex: 1; min-width: 0; overflow-wrap: anywhere; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; }
.directions small { display: block; margin-bottom: 3px; color: #64748b; }
.directions strong { font-weight: 550; }
</style>
