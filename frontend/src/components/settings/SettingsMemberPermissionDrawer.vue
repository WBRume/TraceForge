<script setup lang="ts">
import { ref, watch } from 'vue'
import { X, Loader2 } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import type { PermissionKey, PermissionFlags } from '@/utils/settingsPermissions'
import { defaultPermissionsByRole } from '@/utils/settingsPermissions'

const roleOptions = [
  { value: 'DEVELOPER', label: '开发者 (DEVELOPER)' },
  { value: 'VIEWER', label: '只读成员 (VIEWER)' }
]

interface MemberData {
  id: string
  display_name: string
  email: string
  role: 'OWNER' | 'DEVELOPER' | 'VIEWER'
  is_owner: boolean
  is_expert: boolean
  permissions: PermissionFlags
}

interface PermissionDomain {
  id: string
  name: string
  items: { key: PermissionKey; label: string; desc: string }[]
}

const props = defineProps<{
  visible: boolean
  member: MemberData | null
  saving: boolean
  canManage: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: { permissions: PermissionFlags; isExpert: boolean; role: 'DEVELOPER' | 'VIEWER' }): void
}>()

const PERMISSION_DOMAINS: PermissionDomain[] = [
  {
    id: 'tasks',
    name: '任务流执行',
    items: [
      { key: 'create_task', label: '新建任务', desc: '在当前工作区新建与规划研发任务' },
      { key: 'start_task', label: '启动任务', desc: '触发 Agent 执行与流水线运转' },
      { key: 'manage_task_status', label: '管理任务状态', desc: '暂停、恢复或变更任务运行阶段' },
      { key: 'delete_task', label: '删除任务', desc: '清理已废弃或无效的任务记录' },
      { key: 'export_task', label: '导出任务', desc: '下载任务日志、报表与产物归档' }
    ]
  },
  {
    id: 'assets',
    name: '研发需求与资产',
    items: [
      { key: 'view_dashboard', label: '查看仪表盘', desc: '查看工作区统计度量与项目健康概览' },
      { key: 'view_assets', label: '查看资产', desc: '只读浏览产物仓库与需求库' },
      { key: 'manage_requirements', label: '管理需求资产', desc: '创建、编辑或关联 PRD 与需求条目' },
      { key: 'upload_task_spec', label: '上传规格文档', desc: '上传与更新技术规范和 Prompt 规范' },
      { key: 'manage_skills', label: '管理 Skills', desc: '自定义、调试与维护 Agent Skills 技能库' }
    ]
  },
  {
    id: 'mock',
    name: 'API Mock 协同网关',
    items: [
      { key: 'view_api_mock', label: '查看 API MOCK', desc: '查看接口定义、Mock 数据与响应规则' },
      { key: 'manage_api_mock', label: '管理 API MOCK', desc: '新增、调试与维护 Mock 接口' },
      { key: 'publish_api_mock', label: '发布 API MOCK', desc: '将 Mock 服务推送到网关或共享给外部' }
    ]
  },
  {
    id: 'governance',
    name: '工作区治理与安全',
    items: [
      { key: 'manage_members', label: '管理工作区成员', desc: '邀请团队成员、变更角色与权限分配' }
    ]
  }
]

const localRole = ref<'DEVELOPER' | 'VIEWER'>('VIEWER')
const localIsExpert = ref(false)
const localPerms = ref<PermissionFlags>({} as PermissionFlags)

watch(
  () => props.member,
  (newVal) => {
    if (newVal) {
      localRole.value = newVal.role === 'DEVELOPER' ? 'DEVELOPER' : 'VIEWER'
      localIsExpert.value = Boolean(newVal.is_expert)
      localPerms.value = { ...newVal.permissions }
    }
  },
  { immediate: true, deep: true }
)

const isChecked = (key: PermissionKey) => Boolean(localPerms.value[key])

const togglePerm = (key: PermissionKey) => {
  if (!props.canManage || props.member?.is_owner) return
  localPerms.value[key] = !localPerms.value[key]
}

const isDomainAllChecked = (domain: PermissionDomain) => {
  return domain.items.every(i => Boolean(localPerms.value[i.key]))
}

const toggleDomainAll = (domain: PermissionDomain) => {
  if (!props.canManage || props.member?.is_owner) return
  const allOn = isDomainAllChecked(domain)
  domain.items.forEach(i => {
    localPerms.value[i.key] = !allOn
  })
}

const resetToRoleDefaults = () => {
  if (!props.canManage || props.member?.is_owner) return
  const defaults = defaultPermissionsByRole(localRole.value)
  localPerms.value = { ...defaults }
}

const handleRoleChange = (newRole: 'DEVELOPER' | 'VIEWER') => {
  localRole.value = newRole
  resetToRoleDefaults()
}

const handleSave = () => {
  if (!props.canManage || props.member?.is_owner) return
  emit('save', {
    permissions: { ...localPerms.value },
    isExpert: localIsExpert.value,
    role: localRole.value
  })
}

const avatarInitial = (m: MemberData | null) => {
  if (!m) return '?'
  return (m.display_name || m.email).trim().charAt(0).toUpperCase() || '?'
}
</script>

<template>
  <Teleport to="body">
    <transition name="drawer-fade">
      <div v-if="visible" class="perm-drawer-backdrop" @click="emit('close')">
        <aside class="perm-drawer-container" @click.stop>
          <!-- 抽屉头部 -->
          <header class="perm-drawer-header">
            <div class="perm-drawer-user-info">
              <span class="perm-drawer-avatar" :class="{ 'is-owner': member?.is_owner }">
                {{ avatarInitial(member) }}
              </span>
              <div class="perm-drawer-meta">
                <div class="perm-drawer-title-row">
                  <h3 class="perm-user-title">{{ member?.display_name || member?.email }}</h3>
                  <span class="role-badge" :class="member?.role?.toLowerCase()">
                    {{ member?.is_owner ? '所有者' : member?.role === 'DEVELOPER' ? '开发者' : '只读成员' }}
                  </span>
                  <span v-if="localIsExpert" class="expert-badge-compact">专家</span>
                </div>
                <p class="perm-drawer-sub">{{ member?.email }} · 权限细粒度微调</p>
              </div>
            </div>
            <button type="button" class="perm-drawer-close" :title="$t('common.close')" @click="emit('close')">
              <X class="w-4 h-4" />
            </button>
          </header>

          <!-- 抽屉主体 -->
          <div class="perm-drawer-body">
            <!-- 所有者特殊提示 -->
            <div v-if="member?.is_owner" class="perm-owner-callout">
              <strong>工作区所有者最高权限保护</strong>
              <p>所有者享有工作区所有原子权限与管理特权，不可单独降级或关闭特定权限项。</p>
            </div>

            <!-- 非所有者：角色与专家配置栏 -->
            <div v-if="!member?.is_owner && canManage" class="perm-drawer-pref-strip">
              <div class="perm-pref-item">
                <span class="perm-pref-label">所属角色</span>
                <BaseSelect
                  v-model="localRole"
                  :options="roleOptions"
                  size="sm"
                  class="perm-role-baseselect"
                  @update:model-value="handleRoleChange"
                />
              </div>
              <div class="perm-pref-item">
                <label class="perm-expert-toggle">
                  <input v-model="localIsExpert" type="checkbox">
                  <span class="perm-expert-text">专家认证标签</span>
                </label>
              </div>
            </div>

            <!-- 4 大业务域卡片 -->
            <div class="perm-domains-stack">
              <section
                v-for="domain in PERMISSION_DOMAINS"
                :key="domain.id"
                class="perm-domain-group"
              >
                <div class="perm-domain-head">
                  <div class="perm-domain-info">
                    <span class="perm-domain-title">{{ domain.name }}</span>
                    <span class="perm-domain-count">
                      {{ domain.items.filter(i => isChecked(i.key)).length }}/{{ domain.items.length }}
                    </span>
                  </div>
                  <button
                    v-if="!member?.is_owner && canManage"
                    type="button"
                    class="perm-domain-batch-btn"
                    @click="toggleDomainAll(domain)"
                  >
                    {{ isDomainAllChecked(domain) ? '全部清空' : '本组全选' }}
                  </button>
                </div>

                <div class="perm-items-grid">
                  <div
                    v-for="item in domain.items"
                    :key="item.key"
                    class="perm-item-row"
                    :class="{ 'is-active': isChecked(item.key), 'is-disabled': member?.is_owner || !canManage }"
                    @click="togglePerm(item.key)"
                  >
                    <div class="perm-item-texts">
                      <span class="perm-item-label">{{ item.label }}</span>
                      <span class="perm-item-desc">{{ item.desc }}</span>
                    </div>
                    <div class="perm-item-switch">
                      <input
                        type="checkbox"
                        :checked="isChecked(item.key)"
                        :disabled="member?.is_owner || !canManage"
                        class="perm-switch-input"
                        @click.stop
                        @change="togglePerm(item.key)"
                      >
                    </div>
                  </div>
                </div>
              </section>
            </div>
          </div>

          <!-- 抽屉底部操作栏 -->
          <footer class="perm-drawer-footer">
            <button
              v-if="!member?.is_owner && canManage"
              type="button"
              class="btn-subtle"
              :disabled="saving"
              @click="resetToRoleDefaults"
            >
              恢复角色默认
            </button>
            <div class="perm-drawer-spacer"></div>
            <button
              type="button"
              class="btn-secondary"
              :disabled="saving"
              @click="emit('close')"
            >
              取消
            </button>
            <button
              v-if="!member?.is_owner && canManage"
              type="button"
              class="btn-primary"
              :disabled="saving"
              @click="handleSave"
            >
              <Loader2 v-if="saving" class="w-4 h-4 spin mr-1" />
              <span>{{ saving ? '保存中...' : '保存更改' }}</span>
            </button>
          </footer>
        </aside>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.perm-drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  z-index: 9999;
  display: flex;
  justify-content: flex-end;
}

.perm-drawer-container {
  width: 100%;
  max-width: 520px;
  height: 100vh;
  background: #ffffff;
  box-shadow: -10px 0 36px rgba(15, 23, 42, 0.16);
  display: flex;
  flex-direction: column;
  z-index: 10000;
  animation: permSlideIn 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.perm-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.15rem 1.4rem;
  border-bottom: 1px solid #f1f5f9;
  background: #f8fafc;
}

.perm-drawer-user-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}

.perm-drawer-avatar {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
  color: #ffffff;
  font-weight: 700;
  font-size: 0.95rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.25);
}

.perm-drawer-avatar.is-owner {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  box-shadow: 0 2px 6px rgba(217, 119, 6, 0.3);
}

.perm-drawer-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.perm-drawer-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.perm-user-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.perm-drawer-sub {
  font-size: 0.72rem;
  color: #94a3b8;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.perm-drawer-close {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.18s ease;
}

.perm-drawer-close:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.perm-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem 1.4rem;
  display: flex;
  flex-direction: column;
  gap: 1.15rem;
}

.perm-owner-callout {
  padding: 0.85rem 1rem;
  border-radius: 10px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  color: #b45309;
  font-size: 0.78rem;
}

.perm-owner-callout strong {
  display: block;
  font-weight: 700;
  margin-bottom: 0.25rem;
}

.perm-owner-callout p {
  margin: 0;
  line-height: 1.4;
  color: #92400e;
}

.perm-drawer-pref-strip {
  position: relative;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.perm-pref-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
}

.perm-pref-label {
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}

.perm-role-baseselect {
  width: 205px;
}

.perm-expert-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 600;
  color: #166534;
  user-select: none;
}

.perm-domains-stack {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.perm-domain-group {
  border: 1px solid #edf2f7;
  border-radius: 12px;
  background: #ffffff;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02);
}

.perm-domain-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 0.85rem;
  background: #f8fafc;
  border-bottom: 1px solid #edf2f7;
}

.perm-domain-info {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.perm-domain-title {
  font-weight: 700;
  font-size: 0.82rem;
  color: #1e293b;
}

.perm-domain-count {
  font-size: 0.68rem;
  font-weight: 700;
  color: #0284c7;
  background: #f0f9ff;
  padding: 1px 6px;
  border-radius: 6px;
}

.perm-domain-batch-btn {
  border: none;
  background: transparent;
  color: #0284c7;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0.15rem 0.35rem;
  border-radius: 4px;
  transition: background 0.15s ease;
}

.perm-domain-batch-btn:hover {
  background: rgba(14, 165, 233, 0.08);
}

.perm-items-grid {
  display: flex;
  flex-direction: column;
}

.perm-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid #f8fafc;
  cursor: pointer;
  transition: background 0.15s ease;
}

.perm-item-row:last-child {
  border-bottom: none;
}

.perm-item-row:hover:not(.is-disabled) {
  background: #f8fafc;
}

.perm-item-row.is-active {
  background: #fcfeff;
}

.perm-item-row.is-disabled {
  cursor: not-allowed;
  opacity: 0.75;
}

.perm-item-texts {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
  padding-right: 0.75rem;
}

.perm-item-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: #1e293b;
}

.perm-item-desc {
  font-size: 0.7rem;
  color: #94a3b8;
  line-height: 1.3;
}

.perm-switch-input,
.perm-expert-toggle input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  margin: 0;
  border-radius: 5px;
  border: 1.5px solid #cbd5e1;
  background-color: #ffffff;
  background-repeat: no-repeat;
  background-position: center;
  background-size: 11px 11px;
  cursor: pointer;
  transition: all 0.16s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  outline: none;
  display: inline-block;
  vertical-align: middle;
}

.perm-switch-input:hover:not(:checked):not(:disabled),
.perm-expert-toggle input[type="checkbox"]:hover:not(:checked):not(:disabled) {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.perm-switch-input:checked:hover:not(:disabled),
.perm-expert-toggle input[type="checkbox"]:checked:hover:not(:disabled) {
  border-color: #0284c7;
  background-color: #0284c7;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.35);
}

.perm-switch-input:checked,
.perm-expert-toggle input[type="checkbox"]:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 5px rgba(14, 165, 233, 0.28);
}

.perm-switch-input:focus-visible,
.perm-expert-toggle input[type="checkbox"]:focus-visible {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.22);
}

.perm-switch-input:disabled,
.perm-expert-toggle input[type="checkbox"]:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  background-color: #f8fafc;
  border-color: #cbd5e1;
}

.perm-switch-input:disabled:checked {
  background-color: #94a3b8;
  border-color: #94a3b8;
  box-shadow: none;
}

.perm-drawer-footer {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.9rem 1.4rem;
  border-top: 1px solid #f1f5f9;
  background: #f8fafc;
}

.perm-drawer-spacer {
  flex: 1;
}

/* 按钮规范：统一标准浅蓝色 */
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 0.5rem 1.15rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  background-color: #0ea5e9;
  color: #ffffff;
  border: 1px solid transparent;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.25);
}

.btn-primary:hover:not(:disabled) {
  background-color: #0284c7;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.35);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  background: rgba(15, 23, 42, 0.05);
  color: #475569;
  border: 1px solid rgba(15, 23, 42, 0.08);
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(15, 23, 42, 0.08);
  color: #1e293b;
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-subtle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.45rem 0.75rem;
  border-radius: 8px;
  font-size: 0.76rem;
  font-weight: 600;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  cursor: pointer;
  transition: all 0.18s ease;
}

.btn-subtle:hover:not(:disabled) {
  border-color: #7dd3fc;
  background: #f0f9ff;
  color: #0284c7;
}

.role-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.role-badge.owner {
  background: #fef3c7;
  color: #b45309;
}

.role-badge.developer {
  background: #e0f2fe;
  color: #0369a1;
}

.role-badge.viewer {
  background: #f1f5f9;
  color: #475569;
}

.expert-badge-compact {
  font-size: 0.66rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 6px;
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes permSlideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.drawer-fade-enter-active,
.drawer-fade-leave-active {
  transition: opacity 0.2s ease;
}

.drawer-fade-enter-from,
.drawer-fade-leave-to {
  opacity: 0;
}
</style>
