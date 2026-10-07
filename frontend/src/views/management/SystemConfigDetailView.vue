<!-- Independent configuration route view for each service and workspace setting -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  ArrowLeftIcon,
  ChevronRightIcon,
  FolderIcon,
  AdjustmentsHorizontalIcon,
  MicrophoneIcon,
  MagnifyingGlassIcon,
  ShieldCheckIcon,
  KeyIcon,
  CpuChipIcon,
  ArrowPathIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  XCircleIcon,
  InformationCircleIcon,
} from '@heroicons/vue/24/outline'
import AdminGuard from '@/components/management/AdminGuard.vue'
import FeatureConfigForm from '@/components/system-config/FeatureConfigForm.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import SearchIndexManagement from '@/components/global-search/SearchIndexManagement.vue'
import { useServiceCapabilities, serviceFeatures } from '@/composables/useServiceCapabilities'
import { useSystemConfigStore } from '@/stores/systemConfig'
import { formatApiError } from '@/utils/error'
import type { FeatureConfig, FeatureId } from '@/services/featureConfigApi'

type DetailTarget = FeatureId | 'mgmt' | 'root'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const systemConfigStore = useSystemConfigStore()

const { services, loading: serviceLoading, refresh, applySaved } = useServiceCapabilities()

const currentTarget = computed<DetailTarget>(() => {
  const feat = (route.params.feature as string) || 'speech'
  if (feat === 'mgmt' || feat === 'root') return feat
  if (serviceFeatures.includes(feat as FeatureId)) return feat as FeatureId
  return 'speech'
})

// Workspace settings state
const mgmtEnabled = ref(false)
const workspaceRootDir = ref('')
const loadingStore = ref(false)
const savingMgmt = ref(false)
const savingRoot = ref(false)

const rootDirInvalid = computed(() => {
  const value = workspaceRootDir.value.trim()
  if (!value) return false
  return !(/^[a-zA-Z]:[/\\]/.test(value) || value.startsWith('\\\\') || value.startsWith('/'))
})

const loadStore = async () => {
  loadingStore.value = true
  try {
    await systemConfigStore.load(true)
    mgmtEnabled.value = systemConfigStore.projectProductManagementEnabled
    workspaceRootDir.value = systemConfigStore.workspaceRootDir
  } finally {
    loadingStore.value = false
  }
}

const saveMgmtSelection = async () => {
  if (savingMgmt.value) return
  savingMgmt.value = true
  try {
    await systemConfigStore.updateProjectProductManagementEnabled(mgmtEnabled.value)
    ElMessage.success(t('system_config.saved'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
    await loadStore()
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
    await systemConfigStore.updateWorkspaceRootDir(workspaceRootDir.value.trim())
    ElMessage.success(t('system_config.saved'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
    await loadStore()
  } finally {
    savingRoot.value = false
  }
}

const clearRootDir = () => {
  workspaceRootDir.value = ''
}

const currentService = computed(() => services.value.find(s => s.feature === currentTarget.value))

const targetTitle = computed(() => {
  if (currentTarget.value === 'mgmt') return t('system_config.tab_mgmt_selection')
  if (currentTarget.value === 'root') return t('system_config.tab_workspace_root')
  return currentService.value?.title || t('feature_config.features.' + currentTarget.value)
})

const targetDescription = computed(() => {
  if (currentTarget.value === 'mgmt') return t('system_config.mgmt_selection_desc')
  if (currentTarget.value === 'root') return t('system_config.workspace_root_desc')
  return t('feature_config.subtitle')
})

const targetCategory = computed(() => {
  if (currentTarget.value === 'mgmt' || currentTarget.value === 'root') {
    return t('feature_config.workspace_settings')
  }
  return t('feature_config.title')
})

const targetIcon = computed(() => {
  switch (currentTarget.value) {
    case 'speech': return MicrophoneIcon
    case 'search': return MagnifyingGlassIcon
    case 'diagnosis': return ShieldCheckIcon
    case 'oauth': return KeyIcon
    case 'agent': return CpuChipIcon
    case 'mgmt': return AdjustmentsHorizontalIcon
    case 'root': return FolderIcon
    default: return AdjustmentsHorizontalIcon
  }
})

const onConfigSaved = (config: FeatureConfig, applied: boolean) => {
  applySaved(config)
  ElMessage[applied ? 'success' : 'warning'](t(applied ? 'feature_config.saved' : 'feature_config.apply_pending'))
}

const goBackToOverview = () => {
  void router.push('/management/system')
}

onMounted(() => {
  void loadStore()
})

watch(() => route.params.feature, () => {
  if (currentTarget.value === 'mgmt' || currentTarget.value === 'root') {
    void loadStore()
  }
})
</script>

<template>
  <AdminGuard show-hint>
    <div class="sys-detail-page">
      <!-- Top navigation bar with breadcrumb and fast service switcher -->
      <nav class="detail-nav-bar" aria-label="Breadcrumb">
        <div class="nav-left">
          <button type="button" class="btn-back" @click="goBackToOverview">
            <ArrowLeftIcon class="icon-sm" />
            <span>{{ $t('system_config.title') }}</span>
          </button>
          <div class="breadcrumbs">
            <span class="crumb-link" @click="goBackToOverview">{{ $t('management.nav_system_config') }}</span>
            <ChevronRightIcon class="crumb-sep" />
            <span class="crumb-cat">{{ targetCategory }}</span>
            <ChevronRightIcon class="crumb-sep" />
            <span class="crumb-active">{{ targetTitle }}</span>
          </div>
        </div>
      </nav>

      <!-- Main service header banner -->
      <header class="detail-header-card">
        <div class="header-main-info">
          <div class="header-icon-box">
            <component :is="targetIcon" class="header-icon" />
          </div>
          <div>
            <div class="title-row">
              <h2>{{ targetTitle }}</h2>
              <template v-if="currentService?.capability">
                <span class="status-pill" :class="currentService.capability.status">
                  <i />
                  {{ $t('feature_config.status_' + currentService.capability.status) }}
                </span>
                <span class="mode-tag">{{ $t('feature_config.options.' + currentService.capability.mode, currentService.capability.mode) }}</span>
              </template>
              <span v-else class="source-tag db">{{ $t('feature_config.workspace_settings') }}</span>
            </div>
            <p class="header-desc">{{ targetDescription }}</p>
          </div>
        </div>

        <div v-if="currentService" class="header-actions">
          <button type="button" class="btn-refresh" :disabled="serviceLoading" @click="refresh()">
            <ArrowPathIcon class="icon-sm" :class="{ spinning: serviceLoading }" />
            {{ $t(serviceLoading ? 'feature_config.probing' : 'feature_config.refresh') }}
          </button>
        </div>
      </header>

      <!-- Content grid: Left form area + Right diagnostics panel -->
      <div class="detail-grid">
        <!-- Left: Primary Configuration Forms -->
        <main class="detail-main-content">
          <!-- 1. Platform feature forms (Speech, Search, Diagnosis, OAuth, Agent) -->
          <div v-if="currentService" class="service-form-wrapper">
            <FeatureConfigForm v-if="currentService.config" :config="currentService.config" @saved="onConfigSaved">
              <SearchIndexManagement
                v-if="currentService.feature === 'search'"
                :revision="currentService.config.revision"
                @changed="refresh()"
              />
            </FeatureConfigForm>
            <div v-else class="empty-state">
              <p>{{ $t(serviceLoading ? 'feature_config.probing' : 'feature_config.config_unavailable') }}</p>
            </div>
          </div>

          <!-- 2. Project/Product Management Selection Setting (mgmt) -->
          <div v-else-if="currentTarget === 'mgmt'" class="setting-form-wrapper">
            <section class="setting-card">
              <div class="setting-card-header">
                <div>
                  <h3 class="setting-card-title">{{ $t('system_config.mgmt_selection_label') }}</h3>
                  <p class="setting-card-subtitle">{{ $t('system_config.mgmt_selection_desc') }}</p>
                </div>
                <div class="modern-toggle">
                  <ToggleSwitch
                    v-model="mgmtEnabled"
                    :disabled="loadingStore || savingMgmt"
                    :aria-label="$t('system_config.mgmt_selection_label')"
                  />
                  <span class="toggle-text" :class="{ on: mgmtEnabled }">
                    {{ mgmtEnabled ? $t('system_config.state_on') : $t('system_config.state_off') }}
                  </span>
                </div>
              </div>

              <div class="impact-section">
                <h4 class="impact-title">{{ $t('system_config.mgmt_selection_label') }} - 联动规则矩阵</h4>
                <div class="impact-cards">
                  <div class="impact-item" :class="{ active: mgmtEnabled }">
                    <CheckCircleIcon class="impact-icon green" />
                    <div>
                      <strong>{{ $t('system_config.state_on') }}：</strong>
                      <span>{{ $t('system_config.effect_on') }}</span>
                    </div>
                  </div>
                  <div class="impact-item" :class="{ active: !mgmtEnabled }">
                    <InformationCircleIcon class="impact-icon" />
                    <div>
                      <strong>{{ $t('system_config.state_off') }}（页面可见性）：</strong>
                      <span>{{ $t('system_config.effect_off_pages') }}</span>
                    </div>
                  </div>
                  <div class="impact-item" :class="{ active: !mgmtEnabled }">
                    <InformationCircleIcon class="impact-icon" />
                    <div>
                      <strong>{{ $t('system_config.state_off') }}（命名机制）：</strong>
                      <span>{{ $t('system_config.effect_off_names') }}</span>
                    </div>
                  </div>
                  <div class="impact-item" :class="{ active: !mgmtEnabled }">
                    <InformationCircleIcon class="impact-icon" />
                    <div>
                      <strong>{{ $t('system_config.state_off') }}（分支选择）：</strong>
                      <span>{{ $t('system_config.effect_off_branch') }}</span>
                    </div>
                  </div>
                  <div class="impact-item">
                    <InformationCircleIcon class="impact-icon" />
                    <div>
                      <strong>会话分支继承：</strong>
                      <span>{{ $t('system_config.effect_session_branch') }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <footer class="setting-card-footer">
                <span class="footer-hint">{{ $t('feature_config.form_intro') }}</span>
                <button
                  type="button"
                  class="btn-primary"
                  :disabled="loadingStore || savingMgmt"
                  @click="saveMgmtSelection"
                >
                  {{ savingMgmt ? $t('system_config.saving') : $t('system_config.save') }}
                </button>
              </footer>
            </section>
          </div>

          <!-- 3. Workspace Root Directory Setting (root) -->
          <div v-else-if="currentTarget === 'root'" class="setting-form-wrapper">
            <section class="setting-card">
              <div class="setting-card-header">
                <div>
                  <h3 class="setting-card-title">{{ $t('system_config.workspace_root_label') }}</h3>
                  <p class="setting-card-subtitle">{{ $t('system_config.workspace_root_desc') }}</p>
                </div>
                <span class="source-tag env">WORKSPACE_ROOT_DIR</span>
              </div>

              <div class="field-container">
                <label for="workspace-root-input" class="field-label">{{ $t('system_config.workspace_root_label') }}</label>
                <div class="input-with-action">
                  <input
                    id="workspace-root-input"
                    v-model="workspaceRootDir"
                    type="text"
                    class="form-text-input"
                    :class="{ error: rootDirInvalid }"
                    :placeholder="$t('system_config.workspace_root_placeholder')"
                    :disabled="loadingStore || savingRoot"
                  />
                  <button
                    v-if="workspaceRootDir"
                    type="button"
                    class="btn-clear"
                    :disabled="loadingStore || savingRoot"
                    @click="clearRootDir"
                  >
                    清空以回退 env
                  </button>
                </div>
                <p v-if="rootDirInvalid" class="field-error-hint">
                  {{ $t('system_config.workspace_root_invalid') }}
                </p>
                <p v-else class="field-helper-hint">
                  {{ $t('system_config.workspace_root_effect_env') }}
                </p>
              </div>

              <div class="impact-section">
                <h4 class="impact-title">路径规则安全约束说明</h4>
                <div class="impact-cards">
                  <div class="impact-item active">
                    <CheckCircleIcon class="impact-icon green" />
                    <div>
                      <strong>默认生效位置：</strong>
                      <span>{{ $t('system_config.workspace_root_effect_default') }}</span>
                    </div>
                  </div>
                  <div class="impact-item active">
                    <ShieldCheckIcon class="impact-icon green" />
                    <div>
                      <strong>沙盒防护隔离：</strong>
                      <span>{{ $t('system_config.workspace_root_effect_scope') }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <footer class="setting-card-footer">
                <span class="footer-hint">{{ $t('feature_config.form_intro') }}</span>
                <button
                  type="button"
                  class="btn-primary"
                  :disabled="loadingStore || savingRoot || rootDirInvalid"
                  @click="saveRootDir"
                >
                  {{ savingRoot ? $t('system_config.saving') : $t('system_config.save') }}
                </button>
              </footer>
            </section>
          </div>
        </main>

        <!-- Right: Real-time Health Diagnostics and Guidance Sidebar -->
        <aside class="detail-sidebar">
          <section class="diag-card">
            <header class="diag-card-header">
              <h4 class="diag-card-title">
                <InformationCircleIcon class="icon-sm" />
                连通性与诊断报告
              </h4>
            </header>

            <div v-if="currentService?.capability" class="diag-box" :class="currentService.capability.status">
              <div class="diag-status-name">
                <component
                  :is="currentService.capability.status === 'READY' ? CheckCircleIcon : (currentService.capability.status === 'DEGRADED' ? ExclamationTriangleIcon : XCircleIcon)"
                  class="icon-sm"
                />
                <span>{{ $t('feature_config.status_' + currentService.capability.status) }}</span>
              </div>
              <p class="diag-desc">{{ currentService.capability.explanation }}</p>
              <p v-if="currentService.capability.guidance" class="diag-guidance">
                <strong>建议：</strong> {{ currentService.capability.guidance }}
              </p>
            </div>
            <div v-else class="diag-box neutral">
              <div class="diag-status-name">
                <CheckCircleIcon class="icon-sm" />
                <span>基础设置规则已生效</span>
              </div>
              <p class="diag-desc">工作区基础参数直接作用于平台项目生成器与文件存储底座。</p>
            </div>

            <div class="diag-rules-list">
              <div class="rule-item">
                <span class="rule-bullet" />
                <div>
                  <div class="rule-name">即时热重载</div>
                  <div class="rule-sub">保存后将即刻热生效至调度中心，无需重启服务。</div>
                </div>
              </div>
              <div class="rule-item">
                <span class="rule-bullet" />
                <div>
                  <div class="rule-name">环境兜底继承</div>
                  <div class="rule-sub">未在线覆盖的配置字段将安全继承环境变量默认值。</div>
                </div>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  </AdminGuard>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.sys-detail-page {
  max-width: 1240px;
  margin: 0 auto;
  padding-bottom: 40px;
}

/* Navigation bar */
.detail-nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.btn-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid #dbe4ed;
  border-radius: 8px;
  background: #ffffff;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-back:hover {
  background: #f0f9ff;
  border-color: #0ea5e9;
  color: #0369a1;
}

.breadcrumbs {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
}

.crumb-link {
  cursor: pointer;
  color: #64748b;
  transition: color 0.15s;
}

.crumb-link:hover {
  color: #0284c7;
}

.crumb-sep {
  width: 14px;
  height: 14px;
  color: #94a3b8;
}

.crumb-cat {
  color: #475569;
}

.crumb-active {
  font-weight: 700;
  color: #0f172a;
}

/* Header Card */
.detail-header-card {
  background: #ffffff;
  border: 1px solid #dbe4ed;
  border-radius: 12px;
  padding: 22px 26px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.header-main-info {
  display: flex;
  align-items: center;
  gap: 18px;
}

.header-icon-box {
  width: 50px;
  height: 50px;
  border-radius: 12px;
  background: #f0f9ff;
  color: #0284c7;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.header-icon {
  width: 26px;
  height: 26px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.title-row h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.header-desc {
  margin: 5px 0 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-pill i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-pill.READY {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.status-pill.READY i {
  background: #10b981;
}

.status-pill.DEGRADED {
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fde68a;
}

.status-pill.DEGRADED i {
  background: #f59e0b;
}

.status-pill.NOT_CONFIGURED {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.status-pill.NOT_CONFIGURED i {
  background: #ef4444;
}

.mode-tag {
  font-size: 12px;
  color: #475569;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 4px;
}

.source-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.source-tag.db {
  background: #e0f2fe;
  color: #0369a1;
}

.source-tag.env {
  background: #f1f5f9;
  color: #475569;
}

.btn-refresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-refresh:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #0ea5e9;
  color: #0284c7;
}

/* Grid Layout */
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.5fr) minmax(280px, 1fr);
  gap: 24px;
  align-items: start;
}

@media (max-width: 900px) {
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* Setting Card (mgmt / root) */
.setting-card {
  background: #ffffff;
  border: 1px solid #dbe4ed;
  border-radius: 12px;
  padding: 24px 28px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.setting-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 20px;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 20px;
}

.setting-card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.setting-card-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
}

/* Modern Toggle */
.modern-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  user-select: none;
}

.toggle-text {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  min-width: 48px;
}

.toggle-text.on {
  color: #0369a1;
}

/* Impact Cards */
.impact-section {
  margin: 20px 0;
}

.impact-title {
  font-size: 13px;
  font-weight: 700;
  color: #334155;
  margin: 0 0 12px;
}

.impact-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.impact-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  font-size: 13px;
  color: #475569;
  line-height: 1.6;
}

.impact-item.active {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}

.impact-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  margin-top: 2px;
  color: #94a3b8;
}

.impact-icon.green {
  color: #10b981;
}

/* Field input styling */
.field-container {
  margin-bottom: 22px;
}

.field-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}

.input-with-action {
  display: flex;
  align-items: center;
  gap: 10px;
}

.form-text-input {
  flex: 1;
  height: 42px;
  padding: 0 14px;
  border: 1px solid #dbe4ed;
  border-radius: 8px;
  font-size: 13px;
  color: #0f172a;
  background: #ffffff;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.form-text-input:focus {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.form-text-input.error {
  border-color: #ef4444;
}

.btn-clear {
  padding: 8px 14px;
  border: 1px solid #dbe4ed;
  background: #f8fafc;
  color: #64748b;
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.btn-clear:hover {
  background: #f1f5f9;
  color: #334155;
}

.field-error-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: #dc2626;
}

.field-helper-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: #64748b;
}

.setting-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 18px;
  border-top: 1px solid #f1f5f9;
  margin-top: 22px;
}

.footer-hint {
  font-size: 12px;
  color: #64748b;
}

/* Sidebar Diagnostic Card */
.diag-card {
  background: #ffffff;
  border: 1px solid #dbe4ed;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.diag-card-header {
  margin-bottom: 14px;
}

.diag-card-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 6px;
}

.diag-box {
  padding: 14px;
  border-radius: 8px;
  margin-bottom: 18px;
}

.diag-box.READY {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
}

.diag-box.DEGRADED {
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.diag-box.NOT_CONFIGURED {
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.diag-box.neutral {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.diag-status-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 6px;
}

.diag-box.READY .diag-status-name { color: #065f46; }
.diag-box.DEGRADED .diag-status-name { color: #92400e; }
.diag-box.NOT_CONFIGURED .diag-status-name { color: #991b1b; }
.diag-box.neutral .diag-status-name { color: #334155; }

.diag-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}

.diag-guidance {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

.diag-rules-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}

.rule-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.rule-bullet {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0ea5e9;
  margin-top: 6px;
  flex-shrink: 0;
}

.rule-name {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
}

.rule-sub {
  font-size: 11px;
  color: #64748b;
  line-height: 1.5;
  margin-top: 2px;
}

.icon-sm {
  width: 16px;
  height: 16px;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: #64748b;
  background: #ffffff;
  border-radius: 12px;
  border: 1px solid #dbe4ed;
}
</style>
