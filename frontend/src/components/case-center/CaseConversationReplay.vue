<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loader2, MessageSquareText } from 'lucide-vue-next'
import api from '@/utils/api'

const props = defineProps<{
  wsId: string
  sourceTaskId: string
  snapshot: any[] | null
}>()
const { t } = useI18n()

const messages = ref<any[]>([])
const loading = ref(false)
const isSnapshot = ref(Boolean(Array.isArray(props.snapshot) && props.snapshot.length > 0))

const loadLiveHistory = async () => {
  if (!props.sourceTaskId) return
  loading.value = true
  try {
    const res = await api.get(`/workspaces/${props.wsId}/tasks/${props.sourceTaskId}/history`, {
      params: { page: 1, page_size: 200 },
    })
    const items = Array.isArray(res.data?.messages) ? res.data.messages : []
    messages.value = items.map((m: any) => ({
      role: m.role,
      content: m.content,
      message_type: m.type || 'text',
      created_at: m.created_at,
      creator_display_name: m.creator_display_name || null,
    }))
    isSnapshot.value = false
  } catch (e) {
    console.warn('Failed to load conversation replay', e)
    messages.value = []
  } finally {
    loading.value = false
  }
}

const syncMessages = () => {
  if (Array.isArray(props.snapshot) && props.snapshot.length > 0) {
    messages.value = props.snapshot
    isSnapshot.value = true
    return
  }
  if (props.sourceTaskId) {
    void loadLiveHistory()
    return
  }
  messages.value = []
  isSnapshot.value = false
}

watch(() => [props.snapshot, props.sourceTaskId] as const, syncMessages)
onMounted(syncMessages)
</script>

<template>
  <div class="replay-container">
    <div v-if="loading" class="replay-state">
      <Loader2 class="w-4 h-4 spin" />
      <span>{{ t('common.loading') }}</span>
    </div>

    <div v-else-if="messages.length === 0" class="replay-state">
      <MessageSquareText class="w-5 h-5" />
      <span>{{ t('case_center.replay_empty') }}</span>
    </div>

    <div v-else class="replay-list">
      <div v-for="(msg, idx) in messages" :key="idx" class="replay-msg" :class="`replay-role-${msg.role || 'system'}`">
        <div class="replay-msg-header">
          <span class="replay-role">{{ t(`case_center.role.${msg.role || 'system'}`) }}</span>
          <span v-if="msg.creator_display_name" class="replay-author">{{ msg.creator_display_name }}</span>
          <span v-if="msg.created_at" class="replay-time">{{ new Date(msg.created_at).toLocaleString() }}</span>
        </div>
        <pre class="replay-content">{{ msg.content }}</pre>
      </div>
      <div class="replay-source-note">
        {{ isSnapshot ? t('case_center.replay_snapshot_note') : t('case_center.replay_live_note') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.replay-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.replay-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 0.85rem;
  padding: 24px 0;
}

.replay-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.replay-msg {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  background: #ffffff;
}

.replay-role-user { border-left: 3px solid #3b82f6; }
.replay-role-assistant { border-left: 3px solid #10b981; }
.replay-role-system { border-left: 3px solid #94a3b8; background: #f8fafc; }

.replay-msg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.replay-role {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 999px;
  color: #334155;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}

.replay-role-user .replay-role {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #bfdbfe;
}

.replay-role-assistant .replay-role {
  color: #047857;
  background: #ecfdf5;
  border-color: #a7f3d0;
}

.replay-author {
  font-size: 0.75rem;
  color: #64748b;
}

.replay-time {
  margin-left: auto;
  font-size: 0.7rem;
  color: #94a3b8;
}

.replay-content {
  margin: 0;
  font-family: inherit;
  font-size: 0.85rem;
  line-height: 1.55;
  color: #1e293b;
  white-space: pre-wrap;
  word-break: break-word;
}

.replay-source-note {
  font-size: 0.72rem;
  color: #94a3b8;
  text-align: right;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
