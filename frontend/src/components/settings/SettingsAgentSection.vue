<!-- Workspace-level agent backend selection (claude-code / opencode / dsh). -->
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, Info, Loader2 } from '@/components/icons'
import { useAgentBackendSettings } from '@/composables/useAgentBackendSettings'

const { t } = useI18n()
const vm = useAgentBackendSettings()

const dirty = computed(() => {
  const current = vm.payload.value?.agent_backend || vm.defaultBackend.value
  return vm.selected.value !== current
})
</script>

<template>
  <div class="choice-settings">
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
                <span v-if="option.supports_fork === false" class="no-resume-tag">
                  {{ t('settings.agent.no_fork_tag') }}
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

        <div v-if="!vm.supportsFork.value" class="warning-box mt-4">
          <Info class="w-4 h-4 flex-shrink-0" />
          <span>{{ t('settings.agent.no_fork_warning') }}</span>
        </div>

        <div v-if="vm.error.value" class="error-text mt-4">{{ vm.error.value }}</div>
        <div v-if="vm.success.value" class="success-text mt-4">{{ vm.success.value }}</div>

        <div v-if="vm.testResult.value" class="test-result mt-4" :class="vm.testResult.value.success ? 'success' : 'error'">
          <span class="test-result-label">
            {{ vm.testResult.value.success ? t('settings.agent.test_success') : t('settings.agent.test_failed') }}
          </span>
          <span class="test-result-message">{{ vm.testResult.value.message }}</span>
        </div>

        <div class="actions mt-6">
          <button
            class="btn-secondary"
            :disabled="vm.testing.value || !vm.selected.value"
            @click="vm.testBackend()"
          >
            <Loader2 v-if="vm.testing.value" class="w-4 h-4 spin" />
            {{ vm.testing.value ? t('settings.agent.testing') : t('settings.agent.test') }}
          </button>
          <button
            class="btn-primary"
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
<style scoped src="@/styles/settings/choice-section.css"></style>
<style scoped>
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

.test-result {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.7rem 0.9rem;
  border-radius: 8px;
  font-size: 0.85rem;
  border: 1px solid;
}

.test-result.success {
  color: #15803d;
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.test-result.error {
  color: #b91c1c;
  background: #fef2f2;
  border-color: #fecaca;
}

.test-result-label {
  font-weight: 600;
}

.test-result-message {
  color: inherit;
  word-break: break-word;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.flex-shrink-0 { flex-shrink: 0; }
</style>
