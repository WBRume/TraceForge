<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Eye, FileSearch } from 'lucide-vue-next'
import type { ReviewTarget, ReviewTargetRef, ReviewTargetType } from '@/types/workspaceAssets'

const props = defineProps<{
  targets: ReviewTargetRef[]
  reviewTargets: Record<ReviewTargetType, ReviewTarget[]>
}>()

const emit = defineEmits<{
  preview: [target: ReviewTargetRef]
}>()

const { t, te } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'

const targetLookup = computed(() => {
  const map = new Map<string, ReviewTarget>()
  for (const group of Object.values(props.reviewTargets ?? {})) {
    for (const target of group) {
      map.set(toKey(target), target)
    }
  }
  return map
})

const resolvedTargets = computed(() =>
  props.targets.map((target) => {
    const hydrated = targetLookup.value.get(toKey(target))
    return {
      ...target,
      label: hydrated?.label || target.label || target.target_id,
      status: hydrated?.status ?? null,
      subtitle: hydrated?.subtitle ?? null,
      source_ref: target.source_ref ?? hydrated?.source_ref ?? null,
    }
  }),
)

function toKey(target: Pick<ReviewTargetRef, 'target_type' | 'target_id'>) {
  return `${target.target_type}:${target.target_id}`
}

function targetTypeLabel(type: ReviewTargetType | string) {
  const key = `${baseKey}.target_types.${String(type).toLowerCase()}`
  return te(key) ? t(key) : String(type)
}
</script>

<template>
  <section class="target-context-strip">
    <div class="context-heading">
      <FileSearch class="context-icon" />
      <span>{{ t(`${baseKey}.target_preview.context_title`) }}</span>
    </div>

    <div v-if="resolvedTargets.length" class="target-chip-list">
      <button
        v-for="target in resolvedTargets"
        :key="toKey(target)"
        class="target-chip"
        type="button"
        @click="emit('preview', target)"
      >
        <span class="target-type">{{ targetTypeLabel(target.target_type) }}</span>
        <span class="target-label">{{ target.label }}</span>
        <span v-if="target.status" class="target-status">{{ target.status }}</span>
        <span class="target-action">
          <Eye class="target-action-icon" />
          {{ t(`${baseKey}.target_preview.view_content`) }}
        </span>
      </button>
    </div>

    <p v-else class="context-empty">{{ t(`${baseKey}.target_preview.empty_context`) }}</p>
  </section>
</template>

<style scoped>
.target-context-strip {
  display: grid;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.context-heading {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #475569;
  font-size: 0.75rem;
  font-weight: 800;
}

.context-icon,
.target-action-icon {
  width: 14px;
  height: 14px;
}

.target-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.target-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  min-height: 34px;
  padding: 6px 9px;
  border: 1px solid #dbe4ee;
  border-radius: 8px;
  background: #ffffff;
  color: #0f172a;
  cursor: pointer;
  font-size: 0.78rem;
  text-align: left;
}

.target-chip:hover {
  border-color: #bfdbfe;
  color: #2563eb;
}

.target-type,
.target-status {
  flex: 0 0 auto;
  color: #64748b;
  font-weight: 800;
}

.target-label {
  overflow: hidden;
  max-width: 260px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #2563eb;
  font-weight: 800;
}

.context-empty {
  margin: 0;
  color: #94a3b8;
  font-size: 0.78rem;
}

@media (max-width: 700px) {
  .target-chip {
    width: 100%;
  }

  .target-label {
    max-width: none;
    flex: 1;
  }
}
</style>
