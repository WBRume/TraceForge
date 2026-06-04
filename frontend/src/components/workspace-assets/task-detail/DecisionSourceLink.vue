<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { MessageSquare, FileText, ScrollText, PencilLine } from 'lucide-vue-next'
import type { DecisionSource } from '@/types/workspaceAssets'

const props = defineProps<{
  source?: DecisionSource | null
  workspaceId: string
  taskId: string
}>()

const router = useRouter()
const { t } = useI18n()

const sourceType = computed(() => props.source?.source_type || 'TASK_DETAIL_BACKFILL')
const label = computed(() => {
  const key = `workspace_assets.task_detail.workbench.decision_sources.${sourceType.value}`
  const translated = t(key)
  return translated === key ? (props.source?.label || sourceType.value) : translated
})
const canJump = computed(() => {
  if (sourceType.value === 'CHAT_MESSAGE') return Boolean(props.source?.chat_message_id)
  if (sourceType.value === 'SPEC_PLAN_CHANGE') return Boolean(props.source?.asset_id || props.source?.asset_thread_id)
  if (sourceType.value === 'TASK_CLOSEOUT') return Boolean(props.source?.final_summary_id)
  return false
})
const icon = computed(() => {
  if (sourceType.value === 'CHAT_MESSAGE') return MessageSquare
  if (sourceType.value === 'SPEC_PLAN_CHANGE') return FileText
  if (sourceType.value === 'TASK_CLOSEOUT') return ScrollText
  return PencilLine
})

function jumpToSource() {
  if (!canJump.value) return
  if (sourceType.value === 'CHAT_MESSAGE') {
    router.push({
      name: 'taskChat',
      params: { wsId: props.workspaceId, taskId: props.taskId },
      query: { messageId: props.source?.chat_message_id || undefined },
    })
    return
  }
  if (sourceType.value === 'SPEC_PLAN_CHANGE') {
    router.push({
      name: 'taskChat',
      params: { wsId: props.workspaceId, taskId: props.taskId },
      query: {
        source: 'spec-plan',
        assetId: props.source?.asset_id || undefined,
        threadId: props.source?.asset_thread_id || undefined,
        versionId: props.source?.asset_version_id || undefined,
      },
    })
    return
  }
  router.push({
    name: 'workspaceAssetTaskDetail',
    params: { wsId: props.workspaceId, taskId: props.taskId },
    query: { section: 'finalSummary', finalSummaryId: props.source?.final_summary_id || undefined },
  })
}
</script>

<template>
  <button
    v-if="canJump"
    type="button"
    class="source-link"
    @click.stop="jumpToSource"
  >
    <component :is="icon" class="source-icon" />
    <span>{{ label }}</span>
  </button>
  <span v-else class="source-chip">
    <component :is="icon" class="source-icon" />
    <span>{{ label }}</span>
  </span>
</template>

<style scoped>
.source-link,
.source-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 26px;
  border-radius: 999px;
  padding: 4px 9px;
  font-size: 0.78rem;
  font-weight: 700;
}

.source-link {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  cursor: pointer;
}

.source-link:hover {
  border-color: #60a5fa;
  background: #dbeafe;
}

.source-chip {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
}

.source-icon {
  width: 13px;
  height: 13px;
}
</style>
