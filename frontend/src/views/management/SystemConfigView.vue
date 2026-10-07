<!-- System configuration central hub overview page (Platform Service Matrix & Workspace Settings) -->
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  FolderIcon,
  AdjustmentsHorizontalIcon,
  MicrophoneIcon,
  MagnifyingGlassIcon,
  ShieldCheckIcon,
  KeyIcon,
  CpuChipIcon,
  ArrowPathIcon,
  ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import AdminGuard from '@/components/management/AdminGuard.vue'
import { useServiceCapabilities, type serviceFeatures } from '@/composables/useServiceCapabilities'
import { useSystemConfigStore } from '@/stores/systemConfig'

const router = useRouter()
const systemConfigStore = useSystemConfigStore()

const { services, loading, error, readyCount, refresh } = useServiceCapabilities()

const degradedCount = computed(() => {
  return services.value.filter(item => item.capability?.status === 'DEGRADED').length
})

const getServiceIcon = (feature: (typeof serviceFeatures)[number]) => {
  switch (feature) {
    case 'speech': return MicrophoneIcon
    case 'search': return MagnifyingGlassIcon
    case 'diagnosis': return ShieldCheckIcon
    case 'oauth': return KeyIcon
    case 'agent': return CpuChipIcon
    default: return AdjustmentsHorizontalIcon
  }
}

const goToDetail = (target: string) => {
  void router.push(`/management/system/${target}`)
}

onMounted(() => {
  void systemConfigStore.load(true)
})
</script>

<template>
  <div class="sys-hub-page">
    <div class="mgmt-page-header">
      <div>
        <h2>{{ $t('system_config.title') }}</h2>
        <p class="mgmt-subtitle">{{ $t('feature_config.subtitle') }}</p>
      </div>
      <div class="header-actions">
        <button type="button" class="btn-refresh-hub" :disabled="loading" @click="refresh(true)">
          <ArrowPathIcon class="icon-sm" :class="{ spinning: loading }" />
          <span>{{ $t(loading ? 'feature_config.probing' : 'feature_config.refresh') }}</span>
        </button>
      </div>
    </div>

    <AdminGuard show-hint>
      <!-- Top Overview Metrics Bar -->
      <section class="hub-metrics-row">
        <div class="metric-card">
          <div class="metric-info">
            <span class="metric-indicator-dot" />
            <span class="metric-lbl">受管核心服务</span>
          </div>
          <div class="metric-val">{{ services.length }} <small>项</small></div>
        </div>
        <div class="metric-card">
          <div class="metric-info">
            <span class="metric-indicator-dot success" />
            <span class="metric-lbl">{{ $t('feature_config.ready') }} (READY)</span>
          </div>
          <div class="metric-val text-green">{{ readyCount }} <small>项正常</small></div>
        </div>
        <div class="metric-card">
          <div class="metric-info">
            <span class="metric-indicator-dot warning" :class="{ active: degradedCount > 0 }" />
            <span class="metric-lbl">{{ $t('feature_config.status_DEGRADED') }}</span>
          </div>
          <div class="metric-val" :class="{ 'text-amber': degradedCount > 0 }">
            {{ degradedCount }} <small>项降级</small>
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-info">
            <span class="metric-indicator-dot" />
            <span class="metric-lbl">{{ $t('feature_config.workspace_settings') }}</span>
          </div>
          <div class="metric-val">2 <small>项基础规则</small></div>
        </div>
      </section>

      <p v-if="error" class="hub-error-alert" role="alert">{{ error }}</p>

      <!-- Section: Platform Services Matrix -->
      <section class="hub-section">
        <div class="section-title-bar">
          <div>
            <h3 class="section-title">{{ $t('feature_config.title') }}</h3>
            <p class="section-desc">在线配置云端或本地推理通道，连接连通性与服务健康独立探测</p>
          </div>
          <span class="badge-count">{{ readyCount }} / {{ services.length }} {{ $t('feature_config.ready') }}</span>
        </div>

        <div class="cards-grid">
          <div
            v-for="item in services"
            :key="item.feature"
            class="hub-feature-card"
            role="button"
            tabindex="0"
            @click="goToDetail(item.feature)"
            @keydown.enter="goToDetail(item.feature)"
          >
            <div>
              <div class="card-head">
                <div class="card-brand">
                  <div class="card-icon-box">
                    <component :is="getServiceIcon(item.feature)" class="card-icon" />
                  </div>
                  <div>
                    <h4 class="card-name">{{ item.title }}</h4>
                    <span class="card-id">{{ item.feature }}</span>
                  </div>
                </div>

                <span v-if="item.capability" class="card-status-pill" :class="item.capability.status">
                  <i />
                  {{ $t('feature_config.status_' + item.capability.status) }}
                </span>
                <span v-else class="card-status-pill loading">
                  <i />
                  {{ $t(loading ? 'feature_config.probing' : 'feature_config.status_unknown') }}
                </span>
              </div>

              <div class="card-body">
                <div v-if="item.capability" class="setting-row">
                  <span class="setting-label">当前模式</span>
                  <span
                    class="setting-value"
                    :class="{ disabled: item.capability.status === 'DISABLED' || item.capability.mode === 'off' }"
                  >
                    {{ $t('feature_config.options.' + item.capability.mode, item.capability.mode) }}
                  </span>
                </div>
                <div v-if="item.capability?.explanation" class="prop-explanation">
                  {{ item.capability.explanation }}
                </div>
                <div v-else class="prop-explanation placeholder">
                  {{ $t(loading ? 'feature_config.probing' : 'feature_config.config_unavailable') }}
                </div>
              </div>
            </div>

            <div class="card-foot">
              <span class="foot-hint">{{ item.config ? '参数已就绪' : '默认环境配置' }}</span>
              <div class="btn-goto">
                <span>{{ $t('feature_config.configure') }}</span>
                <ChevronRightIcon class="icon-xs" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Section: Workspace Core Settings -->
      <section class="hub-section">
        <div class="section-title-bar">
          <div>
            <h3 class="section-title">{{ $t('feature_config.workspace_settings') }}</h3>
            <p class="section-desc">集中管控工作区磁盘根目录存储边界与项目产品生成联动规则</p>
          </div>
          <span class="badge-count">2 项基础参数</span>
        </div>

        <div class="cards-grid">
          <!-- Card 1: Project / Product management toggle -->
          <div
            class="hub-feature-card workspace-card"
            role="button"
            tabindex="0"
            @click="goToDetail('mgmt')"
            @keydown.enter="goToDetail('mgmt')"
          >
            <div>
              <div class="card-head">
                <div class="card-brand">
                  <div class="card-icon-box neutral">
                    <AdjustmentsHorizontalIcon class="card-icon" />
                  </div>
                  <div>
                    <h4 class="card-name">{{ $t('system_config.tab_mgmt_selection') }}</h4>
                    <span class="card-id">project-product-mgmt</span>
                  </div>
                </div>
                <span class="card-status-pill" :class="systemConfigStore.projectProductManagementEnabled ? 'READY' : 'DEGRADED'">
                  <i />
                  {{ systemConfigStore.projectProductManagementEnabled ? $t('system_config.state_on') : $t('system_config.state_off') }}
                </span>
              </div>

              <div class="card-body">
                <div class="setting-row">
                  <span class="setting-label">状态</span>
                  <span
                    class="setting-value"
                    :class="{ disabled: !systemConfigStore.projectProductManagementEnabled }"
                  >
                    {{ systemConfigStore.projectProductManagementEnabled ? '已启用规范关联' : '已关闭，自由填写' }}
                  </span>
                </div>
                <p class="prop-explanation">{{ $t('system_config.mgmt_selection_desc') }}</p>
              </div>
            </div>

            <div class="card-foot">
              <span class="foot-hint">平台全局规则</span>
              <div class="btn-goto">
                <span>{{ $t('feature_config.configure') }}</span>
                <ChevronRightIcon class="icon-xs" />
              </div>
            </div>
          </div>

          <!-- Card 2: Workspace root directory -->
          <div
            class="hub-feature-card workspace-card"
            role="button"
            tabindex="0"
            @click="goToDetail('root')"
            @keydown.enter="goToDetail('root')"
          >
            <div>
              <div class="card-head">
                <div class="card-brand">
                  <div class="card-icon-box neutral">
                    <FolderIcon class="card-icon" />
                  </div>
                  <div>
                    <h4 class="card-name">{{ $t('system_config.tab_workspace_root') }}</h4>
                    <span class="card-id">WORKSPACE_ROOT_DIR</span>
                  </div>
                </div>
                <span class="card-status-pill READY">
                  <i />
                  {{ systemConfigStore.workspaceRootDir ? '自定义覆盖' : '环境变量默认' }}
                </span>
              </div>

              <div class="card-body">
                <div class="setting-row">
                  <span class="setting-label">生效路径</span>
                  <span class="setting-value mono">
                    {{ systemConfigStore.workspaceRootDir || 'env 默认路径' }}
                  </span>
                </div>
                <p class="prop-explanation">{{ $t('system_config.workspace_root_desc') }}</p>
              </div>
            </div>

            <div class="card-foot">
              <span class="foot-hint">存储目录隔离约束</span>
              <div class="btn-goto">
                <span>{{ $t('feature_config.configure') }}</span>
                <ChevronRightIcon class="icon-xs" />
              </div>
            </div>
          </div>
        </div>
      </section>
    </AdminGuard>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.sys-hub-page {
  max-width: 1240px;
  margin: 0 auto;
  padding-bottom: 50px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-refresh-hub {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
  transition: all 0.2s ease;
}

.btn-refresh-hub:hover:not(:disabled) {
  background: #f0f9ff;
  border-color: #0ea5e9;
  color: #0369a1;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.15);
}

/* Metrics Row - 紧凑轻量概览指示条，降低视觉权重，不喧宾夺主 */
.hub-metrics-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 22px;
}

@media (max-width: 860px) {
  .hub-metrics-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.metric-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.02);
  transition: all 0.2s ease;
}

.metric-card:hover {
  border-color: #cbd5e1;
}

.metric-info {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.metric-indicator-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
  flex-shrink: 0;
}

.metric-indicator-dot.success {
  background: #10b981;
}

.metric-indicator-dot.warning.active {
  background: #f59e0b;
}

.metric-lbl {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}

.metric-val {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  display: flex;
  align-items: baseline;
  gap: 2px;
  flex-shrink: 0;
}

.metric-val small {
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
}

.metric-val.text-green { color: #166534; }
.metric-val.text-amber { color: #b45309; }

.hub-error-alert {
  padding: 12px 18px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  font-size: 13px;
  margin-bottom: 20px;
}

/* Sections */
.hub-section {
  margin-bottom: 34px;
}

.section-title-bar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 16px;
  gap: 16px;
}

.section-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
}

.section-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
}

.badge-count {
  font-size: 12px;
  font-weight: 600;
  color: #0369a1;
  background: #e0f2fe;
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
}

/* Cards Grid */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.hub-feature-card {
  background: #ffffff;
  border: 1px solid #dbe4ed;
  border-radius: 14px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.03);
}

.hub-feature-card:hover {
  transform: translateY(-2px);
  border-color: #0ea5e9;
  box-shadow: 0 8px 24px rgba(14, 165, 233, 0.12);
}

.hub-feature-card:focus-visible {
  outline: 2px solid #0284c7;
  outline-offset: 2px;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.card-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-icon-box {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: #f0f9ff;
  color: #0284c7;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.2s, color 0.2s;
}

.hub-feature-card:hover .card-icon-box {
  background: #0ea5e9;
  color: #ffffff;
}

.card-icon-box.neutral {
  background: #f1f5f9;
  color: #475569;
}

.hub-feature-card:hover .card-icon-box.neutral {
  background: #334155;
  color: #ffffff;
}

.card-icon {
  width: 22px;
  height: 22px;
}

.card-name {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.card-id {
  display: block;
  font-size: 11px;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.card-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.card-status-pill i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.card-status-pill.READY {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}
.card-status-pill.READY i { background: #10b981; }

.card-status-pill.DEGRADED {
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fde68a;
}
.card-status-pill.DEGRADED i { background: #f59e0b; }

.card-status-pill.NOT_CONFIGURED {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
.card-status-pill.NOT_CONFIGURED i { background: #ef4444; }

.card-status-pill.loading {
  background: #f8fafc;
  color: #64748b;
  border: 1px solid #e2e8f0;
}
.card-status-pill.loading i { background: #94a3b8; }

.card-body {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 16px;
}

/* 工业级配置项只读行规范 */
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.setting-label {
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
  flex-shrink: 0;
}

/* 白底微边框配置生效值槽：扎实专业，绝无浮夸 AI 感 */
.setting-value {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 3px 10px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  letter-spacing: -0.2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 72%;
}

.setting-value.disabled {
  background: #f1f5f9;
  border-color: #e2e8f0;
  color: #94a3b8;
  box-shadow: none;
  font-weight: 500;
}

.setting-value.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11.5px;
}

.prop-explanation {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.prop-explanation.placeholder {
  color: #94a3b8;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}

.foot-hint {
  font-size: 11px;
  color: #94a3b8;
}

.btn-goto {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 700;
  color: #0284c7;
  transition: transform 0.2s;
}

.hub-feature-card:hover .btn-goto {
  transform: translateX(3px);
  color: #0369a1;
}

.icon-sm { width: 16px; height: 16px; }
.icon-xs { width: 14px; height: 14px; }

.spinning { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
