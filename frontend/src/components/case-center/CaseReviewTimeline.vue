<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { History, UserCheck, CheckCircle2, XCircle } from 'lucide-vue-next'

defineProps<{ records: any[] }>()
const { t } = useI18n()

const actionMeta = (action: string) => {
  if (action === 'START') return { icon: UserCheck, cls: 'timeline-start', key: 'case_center.review_action.start' }
  if (action === 'APPROVE') return { icon: CheckCircle2, cls: 'timeline-approve', key: 'case_center.review_action.approve' }
  return { icon: XCircle, cls: 'timeline-reject', key: 'case_center.review_action.reject' }
}
</script>

<template>
  <div class="review-timeline">
    <div v-if="records.length === 0" class="timeline-empty">
      <History class="w-5 h-5" />
      <span>{{ t('case_center.review_records_empty') }}</span>
    </div>

    <div v-else class="timeline-list">
      <div v-for="record in records" :key="record.id" class="timeline-item">
        <div class="timeline-marker" :class="actionMeta(record.action).cls">
          <component :is="actionMeta(record.action).icon" class="w-4 h-4" />
        </div>
        <div class="timeline-body">
          <div class="timeline-title">
            <span class="timeline-action">{{ t(actionMeta(record.action).key) }}</span>
            <span v-if="record.reviewer_name" class="timeline-reviewer">{{ record.reviewer_name }}</span>
            <span v-if="record.created_at" class="timeline-time">{{ new Date(record.created_at).toLocaleString() }}</span>
          </div>
          <p v-if="record.comment" class="timeline-comment">{{ record.comment }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-timeline {
  display: flex;
  flex-direction: column;
}

.timeline-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 0.85rem;
  padding: 24px 0;
}

.timeline-list {
  display: flex;
  flex-direction: column;
  padding-left: 4px;
}

.timeline-item {
  display: flex;
  gap: 12px;
  position: relative;
  padding-bottom: 16px;
}

.timeline-item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 14px;
  top: 30px;
  bottom: 0;
  width: 2px;
  background: #e2e8f0;
}

.timeline-marker {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
}

.timeline-start { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.timeline-approve { color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; }
.timeline-reject { color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; }

.timeline-body {
  min-width: 0;
  flex: 1;
  padding-top: 4px;
}

.timeline-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.timeline-action {
  font-size: 0.85rem;
  font-weight: 700;
  color: #1e293b;
}

.timeline-reviewer {
  font-size: 0.78rem;
  color: #64748b;
}

.timeline-time {
  margin-left: auto;
  font-size: 0.72rem;
  color: #94a3b8;
}

.timeline-comment {
  margin: 4px 0 0;
  font-size: 0.82rem;
  color: #475569;
  line-height: 1.5;
  background: #f8fafc;
  border-radius: 8px;
  padding: 8px 10px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
