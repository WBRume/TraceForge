<!--
SystemConfigView: 系统配置项（管理员）。每个配置项一张卡片：
1. 新建工作区时是否启用“项目管理/产品管理”选择功能。
2. 工作区根目录：默认取 env（WORKSPACE_ROOT_DIR）；界面保存非空值后覆盖 env，清空后回退 env。
   生效时新建工作区路径默认为 根目录/workspace/工作区名称，且仅允许位于该目录之内。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { FolderRoot, SlidersHorizontal } from 'lucide-vue-next'
import AdminGuard from '@/components/management/AdminGuard.vue'
import { formatApiError } from '@/utils/error'
import { useSystemConfigStore } from '@/stores/systemConfig'

const { t } = useI18n()
const systemConfigStore = useSystemConfigStore()

const enabled = ref(false)
const rootDir = ref('')
const loading = ref(false)
const savingMgmt = ref(false)
const savingRoot = ref(false)

const rootDirInvalid = computed(() => {
  const value = rootDir.value.trim()
  if (!value) return false
  // Windows 绝对路径（C:\ 或 C:/ 或 UNC），或 POSIX 绝对路径（/ 开头）
  return !(/^[a-zA-Z]:[/\\]/.test(value) || value.startsWith('\\\\') || value.startsWith('/'))
})

const load = async () => {
  loading.value = true
  try {
    await systemConfigStore.load(true)
    enabled.value = systemConfigStore.projectProductManagementEnabled
    rootDir.value = systemConfigStore.workspaceRootDir
  } finally {
    loading.value = false
  }
}

const saveMgmtSelection = async () => {
  if (savingMgmt.value) return
  savingMgmt.value = true
  try {
    await systemConfigStore.updateProjectProductManagementEnabled(enabled.value)
    ElMessage.success(t('system_config.saved'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
    await load()
  } finally {
    savingMgmt.value = false
  }
}

const saveRootDir = async () => {
  if (savingRoot.value) return
  if (rootDirInvalid.value) {
    ElMessage.error(t('system_config.workspace_root_invalid'))
    return
  }
  savingRoot.value = true
  try {
    await systemConfigStore.updateWorkspaceRootDir(rootDir.value.trim())
    ElMessage.success(t('system_config.saved'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
    await load()
  } finally {
    savingRoot.value = false
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

    <!-- 卡片 1：项目管理/产品管理选择开关 -->
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
            <input v-model="enabled" type="checkbox" :disabled="loading || savingMgmt" />
            <span class="sys-switch-slider"></span>
            <span class="sys-switch-state" :class="{ on: enabled }">
              {{ enabled ? $t('system_config.state_on') : $t('system_config.state_off') }}
            </span>
          </label>
        </AdminGuard>
      </div>

      <AdminGuard>
        <div class="sys-config-actions">
          <button class="btn-primary" :disabled="loading || savingMgmt" @click="saveMgmtSelection">
            {{ savingMgmt ? $t('system_config.saving') : $t('system_config.save') }}
          </button>
        </div>
      </AdminGuard>
    </div>

    <!-- 卡片 2：工作区根目录 -->
    <div class="mgmt-card mgmt-compact-card">
      <div class="sys-config-row">
        <div class="sys-config-info">
          <h3 class="sys-config-name">
            <FolderRoot class="w-4 h-4" />
            {{ $t('system_config.workspace_root_label') }}
          </h3>
          <p class="mgmt-hint">{{ $t('system_config.workspace_root_desc') }}</p>
          <ul class="sys-config-effects">
            <li>{{ $t('system_config.workspace_root_effect_env') }}</li>
            <li>{{ $t('system_config.workspace_root_effect_default') }}</li>
            <li>{{ $t('system_config.workspace_root_effect_scope') }}</li>
          </ul>
        </div>
      </div>

      <AdminGuard>
        <div class="sys-config-field">
          <label>{{ $t('system_config.workspace_root_label') }}</label>
          <input
            v-model="rootDir"
            type="text"
            class="mgmt-input"
            :placeholder="$t('system_config.workspace_root_placeholder')"
            :disabled="loading || savingRoot"
          />
          <p v-if="rootDirInvalid" class="sys-config-input-error">
            {{ $t('system_config.workspace_root_invalid') }}
          </p>
        </div>
        <div class="sys-config-actions">
          <button class="btn-primary" :disabled="loading || savingRoot" @click="saveRootDir">
            {{ savingRoot ? $t('system_config.saving') : $t('system_config.save') }}
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

.sys-config-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-top: 1rem;
}

.sys-config-field label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.sys-config-field .mgmt-input {
  max-width: 480px;
}

.sys-config-input-error {
  margin: 0.35rem 0 0;
  font-size: 0.78rem;
  color: #b91c1c;
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
