<script setup lang="ts">
import { shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, X } from '@/components/icons'
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
  <section class="relation-properties" :aria-label="t('workspace_canvas.menu.properties')">
    <header>
      <h2>{{ t(`workspace_canvas.relations.${link.relation_type}`) }}</h2>
      <button type="button" class="close" :aria-label="t('common.close')" @click="emit('close')"><X :size="18" /></button>
    </header>
    <div class="directions">
      <span><small>{{ t(`workspace_canvas.kind.${link.source.kind}`) }}</small><strong>{{ sourceTitle }}</strong></span>
      <ArrowRight :size="17" />
      <span><small>{{ t(`workspace_canvas.kind.${link.target.kind}`) }}</small><strong>{{ targetTitle }}</strong></span>
    </div>
    <footer v-if="canDetach">
      <el-button type="danger" plain :disabled="saving" @click="confirm = true">{{ t('workspace_canvas.actions.unlink') }}</el-button>
    </footer>
  </section>
  <ConfirmActionModal :show="confirm" :title="t('workspace_canvas.actions.unlink')"
    :message="t('workspace_canvas.actions.detach_document_prompt')" :cancel-text="t('common.cancel')"
    :confirm-text="t('common.confirm')" tone="danger" @cancel="confirm = false" @confirm="detach" />
</template>

<style scoped>
.relation-properties { position: absolute; z-index: 8; top: 18px; right: 16px; width: min(390px, calc(100% - 88px)); padding: 14px; display: grid; gap: 12px; border: 1px solid var(--canvas-line); border-radius: 12px; background: #fff; color: #1e293b; box-shadow: 0 12px 32px #25345928; }
header, footer, .directions { display: flex; align-items: center; gap: 8px; }
header { justify-content: space-between; }
footer { justify-content: flex-end; }
h2 { margin: 0; font-size: 15px; }
.close { display: grid; place-items: center; border: 0; padding: 4px; border-radius: 6px; background: transparent; color: #4b5f76; cursor: pointer; }
.close:hover { background: #edf6ff; }
.directions > span { flex: 1; min-width: 0; overflow-wrap: anywhere; border: 1px solid #e2e8f0; border-radius: 7px; padding: 7px; font-size: 13px; }
.directions small { display: block; margin-bottom: 3px; color: #64748b; }
.directions strong { font-weight: 550; }
</style>
