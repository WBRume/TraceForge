<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementSummary } from '@/types/workspaceAssets'
const props = defineProps<{ requirement: RequirementSummary }>()
const { t } = useI18n()
const prompt = computed(() => props.requirement.task_prompt ?? props.requirement.source_metadata?.task_prompt)
const filename = computed(() => props.requirement.source_metadata?.source_filename)
</script>

<template>
  <section class="requirement-delivery-context">
    <dl class="document-context">
      <div><dt>{{ t('task_rail.document_location') }}</dt><dd>{{ requirement.source_uri || t('task_rail.stored_document') }}</dd></div>
      <div v-if="filename"><dt>{{ t('task_rail.source_document') }}</dt><dd>{{ filename }}</dd></div>
    </dl>
    <h3>{{ t('task_rail.initial_prompt') }}</h3>
    <p class="initial-task-prompt">{{ prompt || t('task_rail.no_prompt') }}</p>
  </section>
</template>

<style scoped>
.requirement-delivery-context { display:grid; gap:14px; min-width:0; }
.document-context { display:grid; gap:12px; margin:0; }
.document-context dt { color:#64748b; font-size:.78rem; margin-bottom:5px; }
.document-context dd { margin:0; color:#334155; overflow-wrap:anywhere; font-size:.85rem; }
h3 { margin:0; color:#0f172a; font-size:.9rem; font-weight:600; }
.initial-task-prompt { margin:0; color:#334155; font-size:.85rem; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.7; }
</style>
