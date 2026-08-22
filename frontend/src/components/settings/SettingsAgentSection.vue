<!-- Workspace-level agent backend selection (claude-code / opencode / dsh). -->
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, Info } from 'lucide-vue-next'
import { useAgentBackendSettings } from '@/composables/useAgentBackendSettings'

const { t } = useI18n()
const vm = useAgentBackendSettings()

const optionLabel = (value: string) => (
  vm.options.value.find((option) => option.value === value)?.label || value
)

const dirty = computed(() => {
  const current = vm.payload.value?.agent_backend || vm.defaultBackend.value
  return vm.selected.value !== current
})
</script>

<template>
  <div class="agent-settings">
    <section class="settings-card glass-panel animate-pop-in">
      <div class="section-title-row">
        <div class="flex items-start gap-4">
          <div class="icon-wrapper">
            <Bot class="w-6 h-6" />
          </div>
          <div>
            <h2 class="title-gradient-small">{{ t('settings.agent.title') }}</h2>
            <p class="subtitle">{{ t('settings.agent.subtitle') }}</p>
          </div>
        </div>
        <span class="mode-pill" :class="{ active: vm.isOverridden.value }">
          {{ vm.isOverridden.value ? t('settings.agent.overridden') : t('settings.agent.follow_default') }}
        </span>
      </div>

      <div v-if="vm.loading.value" class="hint-text mt-4">{{ t('settings.agent.loading') }}</div>

      <template v-else>
        <div class="option-list mt-6">
          <label
            v-for="option in vm.options.value"
            :key="option.value"
            class="option-row"
            :class="{ selected: vm.selected.value === option.value }"
          >
            <input
              v-model="vm.selected.value"
              type="radio"
              name="agent-backend"
              :value="option.value"
            />
            <div class="option-body">
              <div class="option-title">
                <span class="option-name">{{ option.label }}</span>
                <span v-if="option.value === vm.defaultBackend.value" class="default-tag">
                  {{ t('settings.agent.default_tag') }}
                </span>
                <span v-if="!option.supports_resume" class="no-resume-tag">
                  {{ t('settings.agent.no_resume_tag') }}
                </span>
              </div>
              <div class="option-desc">{{ t(`settings.agent.desc_${option.value.replace(/-/g, '_')}`) }}</div>
            </div>
          </label>
        </div>

        <div class="info-box mt-4">
          <Info class="w-4 h-4 flex-shrink-0" />
          <span>{{ t('settings.agent.sticky_note') }}</span>
        </div>

        <div v-if="!vm.supportsResume.value" class="warning-box mt-4">
          <Info class="w-4 h-4 flex-shrink-0" />
          <span>{{ t('settings.agent.no_resume_warning') }}</span>
        </div>

        <div v-if="vm.error.value" class="error-text mt-4">{{ vm.error.value }}</div>
        <div v-if="vm.success.value" class="success-text mt-4">{{ vm.success.value }}</div>

        <div class="actions mt-6">
          <button
            class="save-btn"
            :disabled="vm.saving.value || !dirty"
            @click="vm.save()"
          >
            {{ vm.saving.value ? t('settings.agent.saving') : t('settings.agent.save') }}
          </button>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.agent-settings {
  display: flex;
  flex-direction: column;
  padding-bottom: 2rem;
}

.settings-card {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 16px;
  padding: 1.75rem;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.05);
}

.section-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.title-gradient-small {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: #64748b;
  font-size: 0.9rem;
  margin-top: 0.4rem;
  line-height: 1.5;
}

.icon-wrapper {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
  padding: 0.65rem;
  border-radius: 12px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.2);
  flex-shrink: 0;
}

.mode-pill {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 700;
  white-space: nowrap;
  background: #f8fafc;
}

.mode-pill.active {
  border-color: rgba(16, 185, 129, 0.4);
  color: #047857;
  background: #ecfdf5;
}

.hint-text {
  color: #64748b;
  font-size: 0.875rem;
}

.option-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.option-row {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 0.9rem 1rem;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  background: #fff;
}

.option-row:hover {
  border-color: #93c5fd;
}

.option-row.selected {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.option-row input[type='radio'] {
  margin-top: 0.2rem;
  accent-color: #0ea5e9;
}

.option-body {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.option-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.option-name {
  font-weight: 700;
  color: #1e293b;
  font-size: 0.95rem;
}

.default-tag,
.no-resume-tag {
  border-radius: 999px;
  padding: 0.1rem 0.55rem;
  font-size: 0.72rem;
  font-weight: 700;
}

.default-tag {
  border: 1px solid rgba(14, 165, 233, 0.35);
  color: #0369a1;
  background: #f0f9ff;
}

.no-resume-tag {
  border: 1px solid #fed7aa;
  color: #9a3412;
  background: #fff7ed;
}

.option-desc {
  color: #64748b;
  font-size: 0.82rem;
  line-height: 1.5;
}

.info-box {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  border: 1px solid rgba(14, 165, 233, 0.25);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  background: #f0f9ff;
  color: #075985;
  font-size: 0.875rem;
  font-weight: 500;
  line-height: 1.5;
}

.warning-box {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  background: #fff7ed;
  color: #9a3412;
  font-size: 0.875rem;
  font-weight: 500;
  line-height: 1.5;
}

.error-text {
  color: #dc2626;
  font-size: 0.875rem;
}

.success-text {
  color: #059669;
  font-size: 0.875rem;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.save-btn {
  border: none;
  border-radius: 10px;
  padding: 0.6rem 1.4rem;
  font-weight: 700;
  font-size: 0.9rem;
  color: #fff;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.flex { display: flex; }
.items-start { align-items: flex-start; }
.gap-4 { gap: 1rem; }
.mt-4 { margin-top: 1rem; }
.mt-6 { margin-top: 1.5rem; }
.flex-shrink-0 { flex-shrink: 0; }

@keyframes popIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.animate-pop-in {
  animation: popIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
