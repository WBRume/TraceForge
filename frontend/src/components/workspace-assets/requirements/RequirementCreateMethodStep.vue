<script setup lang="ts">
import { FilePlus2, Link2, UploadCloud } from '@/components/icons'
import { useI18n } from 'vue-i18n'
import type { RequirementCreateStep } from './requirementCreateTypes'

type CreateMethod = Exclude<RequirementCreateStep, 'method' | 'preview'>

const emit = defineEmits<{
  select: [mode: CreateMethod]
}>()

const { t } = useI18n()

const methods: Array<{ key: CreateMethod; icon: typeof FilePlus2; labelKey: string; bodyKey: string; disabled?: boolean }> = [
  {
    key: 'manual',
    icon: FilePlus2,
    labelKey: 'workspace_assets.requirements.create.methods.manual',
    bodyKey: 'workspace_assets.requirements.create.methods.manual_body',
  },
  {
    key: 'file',
    icon: UploadCloud,
    labelKey: 'workspace_assets.requirements.create.methods.file',
    bodyKey: 'workspace_assets.requirements.create.methods.file_body',
  },
  {
    // 外部来源只记录引用、不抓取内容，当前没有实际创建价值，先置灰保留占位
    key: 'source_link',
    icon: Link2,
    labelKey: 'workspace_assets.requirements.create.methods.source_link',
    bodyKey: 'workspace_assets.requirements.create.methods.source_link_body',
    disabled: true,
  },
]

function selectMethod(method: (typeof methods)[number]) {
  if (method.disabled) return
  emit('select', method.key)
}
</script>

<template>
  <section class="method-step">
    <div class="method-grid" :aria-label="t('workspace_assets.requirements.create.method_switcher')">
      <button
        v-for="method in methods"
        :key="method.key"
        type="button"
        class="method-card"
        :class="{ 'is-unavailable': method.disabled }"
        :disabled="method.disabled"
        :aria-disabled="method.disabled ? 'true' : undefined"
        :title="method.disabled ? t('workspace_assets.requirements.create.methods.unavailable_hint') : undefined"
        @click="selectMethod(method)"
      >
        <component :is="method.icon" :size="19" />
        <span>
          <strong>
            {{ t(method.labelKey) }}
            <em v-if="method.disabled" class="unavailable-badge">
              {{ t('workspace_assets.requirements.create.methods.unavailable_badge') }}
            </em>
          </strong>
          <small>{{ t(method.bodyKey) }}</small>
        </span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.method-step {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}


.method-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.method-card {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: white;
  color: #334155;
  text-align: left;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.method-card:hover {
  border-color: #0ea5e9;
  background: #f0f9ff;
  transform: translateY(-2px);
  box-shadow: 0 10px 15px -3px rgba(14, 165, 233, 0.1);
}

.method-card svg {
  flex-shrink: 0;
  margin-top: 0.125rem;
  color: #0ea5e9;
}

.method-card strong {
  display: block;
  font-size: 1rem;
  color: #0f172a;
  margin-bottom: 0.25rem;
}

.method-card small {
  display: block;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.5;
}

/* 未开放的方式：保持占位可见，但明确置灰且不可点击 */
.method-card.is-unavailable,
.method-card.is-unavailable:hover {
  border-color: #e2e8f0;
  background: #f8fafc;
  transform: none;
  box-shadow: none;
  cursor: not-allowed;
}

.method-card.is-unavailable svg {
  color: #cbd5e1;
}

.method-card.is-unavailable strong {
  color: #94a3b8;
}

.method-card.is-unavailable small {
  color: #a8b4c4;
}

.unavailable-badge {
  display: inline-block;
  margin-left: 0.5rem;
  padding: 0 0.4375rem;
  border-radius: 9999px;
  border: 1px dashed #e2e8f0;
  background: #f1f5f9;
  color: #94a3b8;
  font-size: 0.6875rem;
  font-style: normal;
  font-weight: 600;
  line-height: 1.6;
  vertical-align: middle;
}

@media (max-width: 640px) {
  .method-grid {
    grid-template-columns: 1fr;
  }
}
</style>
