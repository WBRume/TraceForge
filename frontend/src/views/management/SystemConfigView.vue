<!--
SystemConfigView: 系统配置项（管理员）。当前提供：
- 新建工作区时是否启用“项目管理/产品管理”选择功能。
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { SlidersHorizontal } from 'lucide-vue-next'
import AdminGuard from '@/components/management/AdminGuard.vue'
import { formatApiError } from '@/utils/error'
import { useSystemConfigStore } from '@/stores/systemConfig'

const { t } = useI18n()
const systemConfigStore = useSystemConfigStore()

const enabled = ref(false)
const saving = ref(false)
const loading = ref(false)

const load = async () => {
  loading.value = true
  try {
    await systemConfigStore.load(true)
    enabled.value = systemConfigStore.projectProductManagementEnabled
  } finally {
    loading.value = false
  }
}

const save = async () => {
  if (saving.value) return
  saving.value = true
  try {
    await systemConfigStore.updateProjectProductManagementEnabled(enabled.value)
    ElMessage.success(t('system_config.saved'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ $t('system_config.title') }}</h2>
        <p class="mgmt-subtitle">{{ $t('system_config.subtitle') }}</p>
      </div>
    </div>

    <div class="mgmt-card mgmt-compact-card">
      <div class="sys-config-row">
        <div class="sys-config-info">
          <h3 class="sys-config-name">
            <SlidersHorizontal class="w-4 h-4" />
            {{ $t('system_config.mgmt_selection_label') }}
          </h3>
          <p class="mgmt-hint">{{ $t('system_config.mgmt_selection_desc') }}</p>
          <ul class="sys-config-effects">
            <li>{{ $t('system_config.effect_on') }}</li>
            <li>{{ $t('system_config.effect_off_pages') }}</li>
            <li>{{ $t('system_config.effect_off_names') }}</li>
            <li>{{ $t('system_config.effect_off_branch') }}</li>
            <li>{{ $t('system_config.effect_session_branch') }}</li>
          </ul>
        </div>
        <AdminGuard>
          <label class="sys-switch">
            <input v-model="enabled" type="checkbox" :disabled="loading || saving" />
            <span class="sys-switch-slider"></span>
            <span class="sys-switch-state" :class="{ on: enabled }">
              {{ enabled ? $t('system_config.state_on') : $t('system_config.state_off') }}
            </span>
          </label>
        </AdminGuard>
      </div>

      <AdminGuard>
        <div class="sys-config-actions">
          <button class="btn-primary" :disabled="loading || saving" @click="save">
            {{ saving ? $t('system_config.saving') : $t('system_config.save') }}
          </button>
        </div>
      </AdminGuard>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.sys-config-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1.5rem;
}

.sys-config-info {
  min-width: 0;
}

.sys-config-name {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}

.sys-config-effects {
  margin: 0.6rem 0 0;
  padding-left: 1.1rem;
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.7;
}

.sys-switch {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  cursor: pointer;
  flex-shrink: 0;
  padding-top: 0.2rem;
}

.sys-switch input {
  display: none;
}

.sys-switch-slider {
  position: relative;
  width: 44px;
  height: 24px;
  border-radius: 999px;
  background: #cbd5e1;
  transition: background 0.2s;
}

.sys-switch-slider::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.25);
  transition: transform 0.2s;
}

.sys-switch input:checked + .sys-switch-slider {
  background: #0ea5e9;
}

.sys-switch input:checked + .sys-switch-slider::after {
  transform: translateX(20px);
}

.sys-switch-state {
  font-size: 0.8rem;
  font-weight: 600;
  color: #64748b;
  min-width: 2.4rem;
}

.sys-switch-state.on {
  color: #0369a1;
}

.sys-config-actions {
  margin-top: 1rem;
  padding-top: 0.9rem;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
</style>
