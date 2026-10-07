<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { CircleHelp } from '@/components/icons'
import { useFeatureConfig } from '@/composables/useFeatureConfig'
import type { FeatureConfig, FeatureId } from '@/services/featureConfigApi'
import { formatApiError } from '@/utils/error'

const props = defineProps<{ config: FeatureConfig }>()
const emit = defineEmits<{ saved: [config: FeatureConfig, applied: boolean] }>()
const { t } = useI18n()
const { values, secretActions, busy, testResult, testStale, invalidSecret, error, updateSecret, setSecretAction, test, save } =
  useFeatureConfig(() => props.config)

const sections: Record<FeatureId, { name: string; keys: string[] }[]> = {
  speech: [
    { name: 'recognition', keys: ['mode', 'region', 'api_key'] },
    { name: 'credentials', keys: ['token_ttl', 'requests_per_minute'] },
  ],
  search: [
    { name: 'retrieval', keys: ['enabled', 'backend', 'workers_enabled'] },
    { name: 'remote_search', keys: ['es_url', 'es_username', 'es_password'] },
    { name: 'vectors', keys: ['embedding_endpoint', 'embedding_model', 'embedding_api_key'] },
  ],
  diagnosis: [{ name: 'execution', keys: ['worker_enabled', 'enforcement'] }],
  oauth: [
    { name: 'github', keys: ['enabled', 'client_id', 'client_secret'] },
    { name: 'callbacks', keys: ['redirect_uri_web', 'redirect_uri_desktop', 'scope'] },
  ],
  agent: [
    { name: 'engine', keys: ['backend'] },
    { name: 'opencode', keys: ['opencode_url', 'opencode_username', 'opencode_password'] },
    { name: 'dsh', keys: ['dsh_url', 'dsh_browser_token', 'dsh_browser_cookie'] },
  ],
}
const groups = computed(() => sections[props.config.feature].map(section => ({
  name: section.name,
  fields: section.keys.flatMap(key => props.config.fields.filter(field => field.key === key)),
})).filter(section => section.fields.length))
const canReset = computed(() => props.config.revision > 0 || props.config.fields.some(field => field.source === 'database'))
const inputId = (key: string) => `feature-${props.config.feature}-${key}`
const secretInput = (key: string, event: Event) => updateSecret(key, (event.target as HTMLInputElement).value)
const optionLabel = (value: string) => t('feature_config.options.' + value, value)

const runTest = async () => {
  try { await test() } catch (err) { error.value = formatApiError(err, t('feature_config.failed'), t) }
}
const runSave = async (reset = false) => {
  try {
    const response = await save(reset)
    if (response) emit('saved', response.config, response.applied)
  } catch (err) { error.value = formatApiError(err, t('feature_config.failed'), t) }
}
</script>

<template>
  <div class="feature-configuration">
    <form class="feature-form" @submit.prevent="runSave()">
      <p v-if="config.error" class="form-error" role="alert">{{ config.error }}</p>
      <fieldset v-for="group in groups" :key="group.name" :disabled="!!busy" class="feature-group">
        <legend>{{ t('feature_config.groups.' + group.name) }}</legend>
        <div class="feature-fields">
          <div v-for="field in group.fields" :key="field.key" class="feature-field"
            :class="{ wide: field.kind === 'secret' || field.kind === 'url' || field.kind === 'https' }">
            <div class="field-heading">
              <div class="field-title">
                <label :for="inputId(field.key)">{{ field.label }}</label>
                <el-tooltip
                  v-if="field.hint"
                  :content="field.hint"
                  placement="top"
                  :show-after="80"
                  popper-class="feature-field-tip"
                >
                  <button
                    type="button"
                    class="field-tip"
                    :aria-label="field.label + '：' + field.hint"
                  >
                    <CircleHelp />
                  </button>
                </el-tooltip>
              </div>
            </div>
            <template v-if="field.kind === 'secret'">
              <input
                :id="inputId(field.key)"
                :value="values[field.key]"
                type="password"
                autocomplete="new-password"
                :maxlength="field.maximum"
                :aria-describedby="inputId(field.key) + '-hint'"
                :placeholder="field.has_value ? String(field.value) : t('feature_config.secret_placeholder')"
                @input="secretInput(field.key, $event)"
              />
              <div class="secret-controls">
                <p :id="inputId(field.key) + '-hint'" class="secret-hint" aria-live="polite">
                  {{ t('feature_config.secret_hint_' + secretActions[field.key]) }}
                </p>
                <div class="secret-actions">
                  <button v-if="secretActions[field.key] !== 'keep'" type="button" class="text-button"
                    @click="setSecretAction(field.key, 'keep')">{{ t('feature_config.undo') }}</button>
                  <button type="button" class="text-button danger" :disabled="secretActions[field.key] === 'clear' || (!field.has_value && !values[field.key])"
                    @click="setSecretAction(field.key, 'clear')">{{ t('feature_config.clear_secret') }}</button>
                </div>
              </div>
            </template>
            <BaseSelect v-else-if="field.kind === 'select'" :id="inputId(field.key)" v-model="values[field.key]"
              :options="field.options.map(value => ({ value, label: optionLabel(value) }))" :disabled="!!busy" />
            <div v-else-if="field.kind === 'boolean'" class="switch-field">
              <ToggleSwitch
                :id="inputId(field.key)"
                :model-value="values[field.key] === true"
                :disabled="!!busy"
                @update:model-value="values[field.key] = $event"
              />
              <span class="switch-state" :class="{ on: values[field.key] === true }">
                {{ t(values[field.key] ? 'feature_config.enabled' : 'feature_config.disabled') }}
              </span>
            </div>
            <input v-else-if="field.kind === 'number'" :id="inputId(field.key)" v-model.number="values[field.key]"
              type="number" :min="field.minimum" :max="field.maximum" required />
            <input v-else :id="inputId(field.key)" v-model="values[field.key]" type="text" :maxlength="field.maximum" />
          </div>
        </div>
      </fieldset>

      <div v-if="testResult" class="probe-result" :class="testResult.status" role="status" aria-live="polite">
        <strong>{{ t('feature_config.status_' + testResult.status) }}</strong>
        <p>{{ testResult.explanation }}</p>
        <p v-if="testResult.guidance" class="probe-guidance">{{ testResult.guidance }}</p>
        <p v-if="testStale" class="stale-result">{{ t('feature_config.test_stale') }}</p>
      </div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>

      <div class="form-actions">
        <span class="action-hint">{{ t('feature_config.form_intro') }}</span>
        <div class="action-buttons">
          <button type="button" class="btn-secondary" :disabled="!!busy || invalidSecret || !!config.error" @click="runTest">
            {{ t(busy === 'test' ? 'feature_config.testing' : 'feature_config.test') }}
          </button>
          <button type="submit" class="btn-primary" :disabled="!!busy || invalidSecret || !!config.error">
            {{ t(busy === 'save' ? 'feature_config.saving' : 'feature_config.save') }}
          </button>
        </div>
      </div>
    </form>
    <slot />
    <details class="reset-config">
      <summary>{{ t('feature_config.reset') }}</summary>
      <p>{{ t('feature_config.reset_hint') }}</p>
      <button type="button" class="btn-secondary" :disabled="!!busy || !canReset" @click="runSave(true)">
        {{ t(busy === 'reset' ? 'feature_config.saving' : 'feature_config.reset') }}
      </button>
    </details>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.feature-configuration { width: 100%; }
.feature-group {
  min-width: 0;
  margin: 0 0 24px;
  padding: 22px 26px;
  border: 1px solid #dbe4ed;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}
.feature-group legend {
  width: 100%;
  padding: 0 0 12px;
  margin-bottom: 20px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.feature-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px 28px; }
.feature-field { min-width: 0; }
.feature-field.wide { grid-column: 1 / -1; }
.field-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 8px; }
.field-heading label { font-size: 13px; font-weight: 600; color: #1e293b; }
.field-title { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.field-tip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: none;
  color: #94a3b8;
  cursor: help;
  transition: color 0.15s, background 0.15s;
}
.field-tip:hover { color: #0284c7; background: #f0f9ff; }
.field-tip:focus-visible { outline: 2px solid #0284c7; outline-offset: 1px; }
.field-tip svg { width: 14px; height: 14px; }
.feature-field input:not([type=checkbox]) {
  box-sizing: border-box;
  width: 100%;
  height: 42px;
  padding: 0 14px;
  border: 1px solid #d7dfe8;
  border-radius: 8px;
  color: #0f172a;
  background: #fff;
  font: inherit;
  font-size: 13px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.feature-field input::placeholder { color: #94a3b8; }
.feature-field input:focus {
  outline: none;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}
.feature-field input:disabled { background: #f8fafc; color: #94a3b8; }

.switch-field {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
}
.switch-state { font-size: 13px; font-weight: 600; color: #94a3b8; }
.switch-state.on { color: #0369a1; }
.secret-hint, .reset-config p { color: #64748b; font-size: 12px; line-height: 1.6; }
.secret-controls { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 4px 16px; margin-top: 8px; }
.secret-hint { margin: 0; }
.secret-actions { display: flex; gap: 14px; flex-wrap: wrap; }
.text-button {
  padding: 0;
  border: 0;
  background: none;
  color: #0284c7;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}
.text-button:hover { text-decoration: underline; color: #0369a1; }
.text-button.danger { color: #dc2626; }
.text-button.danger:hover { color: #b91c1c; }
.text-button:disabled { color: #94a3b8; cursor: default; text-decoration: none; }

.probe-result {
  padding: 16px 20px;
  border: 1px solid #fcd34d;
  border-radius: 10px;
  background: #fffbeb;
  font-size: 13px;
  margin-bottom: 20px;
}
.probe-result.READY { border-color: #a7f3d0; background: #ecfdf5; }
.probe-result.DEGRADED { border-color: #fde68a; background: #fffbeb; }
.probe-result.NOT_CONFIGURED { border-color: #fecaca; background: #fef2f2; }
.probe-result strong { display: block; font-size: 14px; margin-bottom: 4px; }
.probe-result.READY strong { color: #065f46; }
.probe-result.DEGRADED strong { color: #92400e; }
.probe-result.NOT_CONFIGURED strong { color: #991b1b; }
.probe-result p { margin: 4px 0 0; line-height: 1.6; color: #334155; }
.probe-guidance { color: #64748b; }

.form-error, .stale-result { color: #b91c1c; font-size: 13px; line-height: 1.6; margin: 10px 0; }

.form-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin: 24px 0;
  padding: 18px 24px;
  background: #ffffff;
  border: 1px solid #dbe4ed;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}
.action-hint { font-size: 12px; color: #64748b; }
.action-buttons { display: flex; flex-wrap: wrap; gap: 12px; }

.reset-config {
  margin-top: 24px;
  padding: 16px 20px;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  background: #f8fafc;
}
.reset-config summary {
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.reset-config p { margin: 8px 0 14px; }

@media (max-width: 650px) {
  .feature-fields { grid-template-columns: minmax(0, 1fr); }
  .form-actions { align-items: stretch; }
  .action-buttons { width: 100%; }
  .action-buttons button { flex: 1; justify-content: center; }
}
</style>

<style>
.feature-field-tip.el-popper {
  max-width: 340px;
  line-height: 1.7;
  font-size: 12px;
  white-space: pre-line;
}
</style>
