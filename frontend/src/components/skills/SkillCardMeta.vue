<script setup lang="ts">
import { computed } from 'vue'
import { FolderOpen, Wrench } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

import type { SkillItem } from '@/composables/skills/useSkillsListQuery'

const props = defineProps<{
  skill: SkillItem
  creatorName: string
  lastModifierName: string
  workspaceName: string
}>()

const { t } = useI18n()
const isUnpublished = computed(() => (
  Boolean(props.skill.has_pending_changes || props.skill.publish_state === 'DRAFT')
))
</script>

<template>
  <div class="skill-meta">
    <div class="meta-line">
      <span class="meta-item">
        <Wrench class="meta-icon" />
        {{ skill.can_manage ? t('skills.list.manage') : t('skills.list.read_only') }}
      </span>
      <span v-if="skill.source_locked" class="status-badge official">{{ t('skills.list.official_source') }}</span>
      <span v-if="isUnpublished" class="status-badge draft">{{ t('skills.list.unpublished') }}</span>
      <span class="meta-item">{{ t('skills.list.version') }}: v{{ skill.latest_version_no || 0 }}</span>
    </div>

    <div class="meta-line">
      <span class="meta-item">{{ t('skills.list.creator') }}: {{ creatorName }}</span>
      <span class="meta-item">{{ t('skills.list.last_modifier') }}: {{ lastModifierName }}</span>
    </div>

    <div class="meta-line">
      <span class="meta-item">{{ t('skills.list.rating') }}: {{ skill.average_score ?? '-' }} ({{ skill.review_count }})</span>
    </div>

    <div v-if="skill.dimension === 'WORKSPACE'" class="meta-line meta-line-workspace">
      <span class="meta-item">
        <FolderOpen class="meta-icon" />
        {{ t('skills.editor.target_workspace') }}: {{ workspaceName || '-' }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.skill-meta {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.7rem;
  min-width: 0;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  color: #64748b;
  font-size: 0.75rem;
  min-width: 0;
  white-space: normal;
  word-break: break-word;
}

.meta-line-workspace .meta-item {
  color: #166534;
}

.meta-icon {
  width: 0.75rem;
  height: 0.75rem;
  flex-shrink: 0;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.08rem 0.5rem;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.status-badge.draft {
  color: #92400e;
  background: #fef3c7;
  border: 1px solid #fcd34d;
}

.status-badge.official {
  color: #075985;
  background: #e0f2fe;
  border: 1px solid #7dd3fc;
}
</style>
