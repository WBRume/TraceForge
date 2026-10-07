<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { RefreshCw, FolderRoot, SlidersHorizontal } from '@/components/icons'
import FeatureConfigForm from './FeatureConfigForm.vue'
import SearchIndexManagement from '@/components/global-search/SearchIndexManagement.vue'
import { useServiceCapabilities } from '@/composables/useServiceCapabilities'
import type { FeatureConfig, FeatureId } from '@/services/featureConfigApi'

type ConfigTab = FeatureId | 'mgmt' | 'root'
const { t } = useI18n()
const active = shallowRef<ConfigTab>('speech')
const { services, loading, error, readyCount, refresh, applySaved } = useServiceCapabilities()
const basicTabs = computed(() => [
  { key: 'mgmt' as const, title: t('system_config.tab_mgmt_selection'), icon: SlidersHorizontal },
  { key: 'root' as const, title: t('system_config.tab_workspace_root'), icon: FolderRoot },
])
const selected = computed(() => services.value.find(item => item.feature === active.value))
const saved = (config: FeatureConfig, applied: boolean) => {
  applySaved(config)
  ElMessage[applied ? 'success' : 'warning'](t(applied ? 'feature_config.saved' : 'feature_config.apply_pending'))
}
const moveTab = (event: KeyboardEvent) => {
  const keys: ConfigTab[] = [...services.value.map(item => item.feature), 'mgmt', 'root']
  const index = keys.indexOf(active.value)
  let next = index
  if (event.key === 'ArrowRight') next = (index + 1) % keys.length
  else if (event.key === 'ArrowLeft') next = (index + keys.length - 1) % keys.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = keys.length - 1
  else return
  event.preventDefault()
  active.value = keys[next]!
  const tabs = (event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]')
  tabs[next]?.focus()
}
</script>

<template>
  <section class="system-configuration" :aria-label="t('feature_config.title')">
    <header class="matrix-header">
      <div>
        <h3>{{ t('feature_config.title') }} <span class="ready-count">
          {{ readyCount }} / {{ services.length }} {{ t('feature_config.ready') }}
        </span></h3>
        <p>{{ t('feature_config.subtitle') }}</p>
      </div>
      <button type="button" class="btn-secondary" :disabled="loading" @click="refresh()">
        <RefreshCw :size="14" :class="{ spinning: loading }" />
        {{ t(loading ? 'feature_config.probing' : 'feature_config.refresh') }}
      </button>
    </header>
    <p v-if="error" class="matrix-error" role="alert">{{ error }}</p>
    <div class="configuration-tabs" role="tablist" :aria-label="t('system_config.title')" @keydown="moveTab">
      <button v-for="item in services" :id="'config-tab-' + item.feature" :key="item.feature" type="button" role="tab"
        class="configuration-tab service-tab" :class="{ active: active === item.feature }" :aria-selected="active === item.feature"
        :aria-controls="'config-panel-' + item.feature" :tabindex="active === item.feature ? 0 : -1" @click="active = item.feature">
        <span class="tab-title">{{ item.title }}</span>
        <span class="status-tag" :class="item.capability?.status"><i />
          {{ item.capability ? t('feature_config.status_' + item.capability.status) : t(loading ? 'feature_config.probing' : 'feature_config.status_unknown') }}
        </span>
      </button>
      <button v-for="item in basicTabs" :id="'config-tab-' + item.key" :key="item.key" type="button" role="tab"
        class="configuration-tab basic-tab" :class="{ active: active === item.key }" :aria-selected="active === item.key"
        :aria-controls="'config-panel-' + item.key" :tabindex="active === item.key ? 0 : -1" @click="active = item.key">
        <span class="tab-title">{{ item.title }}</span>
        <span class="basic-caption"><component :is="item.icon" :size="12" />{{ t('feature_config.workspace_settings') }}</span>
      </button>
    </div>
    <div class="configuration-content">
      <header v-if="selected" class="section-header">
        <div class="section-heading">
          <h3>{{ selected.title }}</h3>
          <span v-if="selected.capability" class="mode">{{ t('feature_config.options.' + selected.capability.mode, selected.capability.mode) }}</span>
        </div>
        <div v-if="selected.capability" class="service-diagnosis" :class="selected.capability.status">
          <p>{{ selected.capability.explanation }}</p>
          <p v-if="selected.capability.guidance" class="guidance">{{ selected.capability.guidance }}</p>
        </div>
      </header>
      <div v-for="item in services" v-show="active === item.feature" :id="'config-panel-' + item.feature" :key="item.feature"
        role="tabpanel" :aria-labelledby="'config-tab-' + item.feature">
        <FeatureConfigForm v-if="item.config" :config="item.config" @saved="saved">
          <SearchIndexManagement v-if="item.feature === 'search' && active === 'search'" :revision="item.config.revision" @changed="refresh()" />
        </FeatureConfigForm>
        <p v-else class="matrix-empty">{{ t(loading ? 'feature_config.probing' : 'feature_config.config_unavailable') }}</p>
      </div>
      <div v-for="item in basicTabs" v-show="active === item.key" :id="'config-panel-' + item.key" :key="item.key"
        class="basic-panel" role="tabpanel" :aria-labelledby="'config-tab-' + item.key">
        <slot :name="item.key" />
      </div>
    </div>
  </section>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.system-configuration { overflow: hidden; border: 1px solid #dbe4ed; border-radius: 10px; background: #fff; }
.matrix-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 22px 24px; }
.matrix-header h3 { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 0; color: #0f172a; font-size: 16px; }
.matrix-header p { margin: 7px 0 0; font-size: 12px; line-height: 1.6; color: #64748b; }
.ready-count { font-size: 11px; color: #475569; font-weight: 500; }
.matrix-header button { flex-shrink: 0; display: inline-flex; align-items: center; gap: 7px; }
.configuration-tabs { display: flex; padding: 0 24px; overflow-x: auto; border-bottom: 1px solid #e2e8f0; scrollbar-width: thin; }
.configuration-tab { position: relative; display: flex; flex: 1 0 auto; flex-direction: column; align-items: flex-start; gap: 9px; min-width: 112px; padding: 15px 16px 18px; border: 0; background: none; color: #64748b; font: inherit; cursor: pointer; transition: color .15s, background .15s; }
.configuration-tab:hover { color: #0f172a; background: #f8fafc; }
.configuration-tab.active { color: #0369a1; background: #f0f9ff; }
.configuration-tab.active::after { content: ''; position: absolute; inset: auto 0 0; height: 2px; background: #0284c7; }
.configuration-tab:focus-visible { outline: 2px solid #0284c7; outline-offset: -2px; }
.tab-title { white-space: nowrap; font-size: 13px; font-weight: 600; }
.service-tab + .basic-tab { margin-left: 12px; }.basic-caption { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #94a3b8; }
.status-tag { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; font-size: 11px; color: #64748b; }
.status-tag i { height: 6px; width: 6px; border-radius: 50%; background: #94a3b8; }
.status-tag.READY { color: #047857; }.status-tag.READY i { background: #10b981; }
.status-tag.DEGRADED { color: #b45309; }.status-tag.DEGRADED i { background: #f59e0b; }
.status-tag.NOT_CONFIGURED { color: #b91c1c; }.status-tag.NOT_CONFIGURED i { background: #ef4444; }
.configuration-content { padding: 28px 40px 32px; }
.section-header, .basic-panel { max-width: 900px; }
.section-header { margin-bottom: 28px; }.section-heading { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.section-heading h3 { margin: 0; color: #0f172a; font-size: 18px; font-weight: 600; }
.mode { font-size: 12px; color: #64748b; }
.service-diagnosis { margin-top: 14px; padding-left: 12px; border-left: 2px solid #cbd5e1; }
.service-diagnosis.READY { border-color: #10b981; }.service-diagnosis.DEGRADED { border-color: #f59e0b; }.service-diagnosis.NOT_CONFIGURED { border-color: #ef4444; }
.service-diagnosis p { margin: 0; color: #475569; font-size: 12px; line-height: 1.8; }.service-diagnosis .guidance { color: #64748b; }
.matrix-error { margin: 0 24px 14px; color: #b91c1c; font-size: 13px; }.matrix-empty { color: #64748b; font-size: 13px; }
.spinning { animation: spin 1s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 700px) {
  .matrix-header { padding: 18px 16px; flex-wrap: wrap; }.matrix-header button { align-self: flex-start; }
  .configuration-tabs { padding: 0 8px; }.configuration-tab { min-width: 114px; padding-inline: 12px; }
  .configuration-content { padding: 24px 16px; }
}
@media (prefers-reduced-motion: reduce) { .spinning { animation: none; }.configuration-tab { transition: none; } }
</style>
