<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessageCircle, MessageSquarePlus, SendHorizontal } from 'lucide-vue-next'
import type { ClarificationMessagePayload, ClarificationMessageType } from '@/types/workspaceAssets'

defineProps<{
  saving: boolean
}>()

const emit = defineEmits<{
  submit: [payload: ClarificationMessagePayload]
}>()

const { t } = useI18n()
const composer = reactive({
  entryType: null as Extract<ClarificationMessageType, 'FOLLOW_UP' | 'ANSWER'> | null,
  body: '',
})

const composerPlaceholder = computed(() =>
  composer.entryType === 'ANSWER'
    ? t('workspace_assets.task_detail.final_workflow.clarification.answer_placeholder')
    : t('workspace_assets.task_detail.final_workflow.clarification.follow_up_placeholder'),
)

function openComposer(entryType: Extract<ClarificationMessageType, 'FOLLOW_UP' | 'ANSWER'>) {
  composer.entryType = entryType
  composer.body = ''
}

function submitMessage() {
  if (!composer.entryType || !composer.body.trim()) return
  emit('submit', {
    body: composer.body,
    entry_type: composer.entryType,
  })
  composer.body = ''
  composer.entryType = null
}
</script>

<template>
  <footer class="composer">
    <div class="composer-actions">
      <el-button
        :disabled="saving"
        :type="composer.entryType === 'FOLLOW_UP' ? 'primary' : 'default'"
        plain
        @click="openComposer('FOLLOW_UP')"
      >
        <MessageSquarePlus class="button-icon" />
        {{ t('workspace_assets.task_detail.final_workflow.clarification.follow_up') }}
      </el-button>
      <el-button
        :disabled="saving"
        :type="composer.entryType === 'ANSWER' ? 'primary' : 'default'"
        plain
        @click="openComposer('ANSWER')"
      >
        <MessageCircle class="button-icon" />
        {{ t('workspace_assets.task_detail.final_workflow.clarification.answer') }}
      </el-button>
    </div>
    <div v-if="composer.entryType" class="composer-input-row">
      <el-input
        v-model="composer.body"
        type="textarea"
        :rows="3"
        :disabled="saving"
        :placeholder="composerPlaceholder"
      />
      <el-button
        type="primary"
        :disabled="!composer.body.trim() || saving"
        :loading="saving"
        @click="submitMessage"
      >
        <SendHorizontal class="button-icon" />
        {{ t('workspace_assets.task_detail.final_workflow.clarification.send') }}
      </el-button>
    </div>
  </footer>
</template>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
}

.composer-actions,
.composer-input-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.composer-input-row :deep(.el-textarea) {
  flex: 1 1 auto;
}

.button-icon {
  width: 15px;
  height: 15px;
  margin-right: 6px;
}

@media (max-width: 700px) {
  .composer-input-row {
    flex-direction: column;
  }
}
</style>
