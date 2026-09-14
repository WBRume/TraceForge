<script setup lang="ts">
import { onMounted, onUnmounted, proxyRefs, ref } from 'vue'
import { ChevronDown, Loader2, Search } from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import SettingsMemberPermissionDrawer from './SettingsMemberPermissionDrawer.vue'
import type { PermissionFlags } from '@/utils/settingsPermissions'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)

type MemberRole = 'OWNER' | 'DEVELOPER' | 'VIEWER'

type MemberRow = {
  id: string
  workspace_id: string
  user_id: string
  email: string
  display_name: string
  role: MemberRole
  joined_at: string
  is_owner: boolean
  is_expert: boolean
  permissions: PermissionFlags
}

const avatarInitial = (member: MemberRow) => (
  (member.display_name || member.email).trim().charAt(0).toUpperCase() || '?'
)

// 4 大原子权限业务域统计计算
const taskCount = (p?: PermissionFlags) => {
  if (!p) return 0
  return [p.create_task, p.start_task, p.manage_task_status, p.delete_task, p.export_task].filter(Boolean).length
}

const assetCount = (p?: PermissionFlags) => {
  if (!p) return 0
  return [p.view_dashboard, p.view_assets, p.manage_requirements, p.upload_task_spec, p.manage_skills].filter(Boolean).length
}

const mockCount = (p?: PermissionFlags) => {
  if (!p) return 0
  return [p.view_api_mock, p.manage_api_mock, p.publish_api_mock].filter(Boolean).length
}

const govCount = (p?: PermissionFlags) => {
  if (!p) return 0
  return p.manage_members ? 1 : 0
}

// 角色快捷下拉菜单管理
const roleMenuOpenId = ref('')

const toggleRoleMenu = (memberId: string) => {
  roleMenuOpenId.value = roleMenuOpenId.value === memberId ? '' : memberId
}

const closeRoleMenu = () => {
  roleMenuOpenId.value = ''
}

const pickRole = async (member: MemberRow, value: 'DEVELOPER' | 'VIEWER') => {
  vm.startEditMember(member)
  const draft = vm.memberDrafts[member.id]
  if (draft) {
    draft.role = value
    vm.applyDraftRoleDefaults(member.id)
    await vm.saveMember(member)
  }
  roleMenuOpenId.value = ''
}

// 权限微调侧滑抽屉控制
const drawerVisible = ref(false)
const drawerEditingMember = ref<MemberRow | null>(null)

const openPermissionDrawer = (member: MemberRow) => {
  vm.startEditMember(member)
  drawerEditingMember.value = member
  drawerVisible.value = true
}

const handleDrawerSave = async (payload: {
  permissions: PermissionFlags
  isExpert: boolean
  role: 'DEVELOPER' | 'VIEWER'
}) => {
  if (!drawerEditingMember.value) return
  const member = drawerEditingMember.value
  const draft = vm.memberDrafts[member.id]
  if (draft) {
    draft.permissions = payload.permissions
    draft.is_expert = payload.isExpert
    draft.role = payload.role
    await vm.saveMember(member)
  }
  drawerVisible.value = false
}

// 快速切换专家标签
const quickToggleExpert = async (member: MemberRow) => {
  if (!vm.canManageMembers || member.is_owner) return
  vm.startEditMember(member)
  const draft = vm.memberDrafts[member.id]
  if (draft) {
    draft.is_expert = !member.is_expert
    await vm.saveMember(member)
  }
}

onMounted(() => {
  window.addEventListener('click', closeRoleMenu)
})

onUnmounted(() => {
  window.removeEventListener('click', closeRoleMenu)
})
</script>

<template>
  <section class="member-console-panel">
    <!-- 顶部操作工具栏 -->
    <div class="member-toolbar">
      <div class="member-search-box">
        <Search class="member-search-icon" />
        <input
          v-model="vm.memberKeywordInput"
          class="member-search-input"
          type="text"
          :placeholder="$t('settings.members.search_placeholder')"
          @keyup.enter="vm.runMemberSearch"
        >
        <button
          v-if="vm.memberKeywordQuery"
          class="member-view-chip"
          :disabled="vm.loadingMembers"
          @click="vm.clearMemberSearch"
        >
          {{ $t('settings.members.clear_search') }}
        </button>
      </div>

      <div class="member-toolbar-spacer"></div>
      <button v-if="vm.canManageMembers" class="btn-secondary" @click="vm.openAddModal">
        {{ $t('settings.members.batch_add') }}
      </button>
      <button v-if="vm.canManageMembers" class="btn-primary" @click="vm.openAddModal">
        {{ $t('settings.members.invite_members') }}
      </button>
    </div>

    <!-- 视图分类 Tabs 与分页指示 -->
    <div class="member-views-row">
      <div class="member-views">
        <button
          class="member-view-chip"
          :class="{ active: vm.memberViewFilter === 'all' }"
          @click="vm.memberViewFilter = 'all'"
        >
          {{ $t('settings.members.views_all') }}
          <span class="view-count">{{ vm.memberViewCounts.all }}</span>
        </button>
        <button
          class="member-view-chip"
          :class="{ active: vm.memberViewFilter === 'owner' }"
          @click="vm.memberViewFilter = 'owner'"
        >
          {{ $t('settings.members.views_owner') }}
          <span class="view-count">{{ vm.memberViewCounts.owner }}</span>
        </button>
        <button
          class="member-view-chip"
          :class="{ active: vm.memberViewFilter === 'developer' }"
          @click="vm.memberViewFilter = 'developer'"
        >
          {{ $t('settings.members.views_developer') }}
          <span class="view-count">{{ vm.memberViewCounts.developer }}</span>
        </button>
        <button
          class="member-view-chip"
          :class="{ active: vm.memberViewFilter === 'viewer' }"
          @click="vm.memberViewFilter = 'viewer'"
        >
          {{ $t('settings.members.views_viewer') }}
          <span class="view-count">{{ vm.memberViewCounts.viewer }}</span>
        </button>
        <button
          class="member-view-chip"
          :class="{ active: vm.memberViewFilter === 'expert' }"
          @click="vm.memberViewFilter = 'expert'"
        >
          {{ $t('settings.members.views_expert') }}
          <span class="view-count">{{ vm.memberViewCounts.expert }}</span>
        </button>
      </div>
      <div class="member-toolbar-spacer"></div>
      <span class="member-view-chip is-static">
        {{ $t('settings.members.page_info', { page: vm.memberPage, total: vm.totalMemberPages }) }}
      </span>
    </div>

    <!-- 批量全选表头条 -->
    <div v-if="vm.canManageMembers && vm.filteredConsoleMembers.length" class="member-batch-header-strip">
      <label class="batch-select-all-label">
        <input
          type="checkbox"
          class="member-check"
          :checked="vm.allFilteredSelected"
          :indeterminate="vm.someFilteredSelected"
          :disabled="vm.selectableFilteredCount === 0"
          @click.stop
          @change="vm.toggleSelectAllFiltered"
        >
        <span>全选当前页成员 ({{ vm.filteredConsoleMembers.length }})</span>
      </label>
      <span class="batch-hint">点击每行“微调权限”即可侧滑微调 14 项原子权限</span>
    </div>

    <!-- 悬浮行卡槽列表 (Floating Row Pods) -->
    <div v-if="vm.loadingMembers" class="member-loading-block">
      <Loader2 class="w-6 h-6 spin text-primary" />
      <span>{{ $t('settings.members.loading') }}</span>
    </div>

    <div v-else-if="!vm.filteredConsoleMembers.length" class="member-empty-block">
      <p class="member-empty-text">{{ $t('settings.members.empty') }}</p>
    </div>

    <div v-else class="member-pods-container">
      <article
        v-for="member in vm.filteredConsoleMembers"
        :key="member.id"
        class="member-pod-card"
        :class="{
          'is-owner': member.is_owner,
          'is-selected': vm.isMemberSelected(member.id),
          'has-open-menu': roleMenuOpenId === member.id
        }"
      >
        <!-- 左侧身份区 -->
        <div class="pod-identity-section">
          <input
            v-if="vm.canManageMembers && !member.is_owner"
            type="checkbox"
            class="member-check"
            :checked="vm.isMemberSelected(member.id)"
            @change="vm.toggleMemberSelected(member.id)"
          >
          <span class="pod-avatar" :class="{ 'is-owner': member.is_owner }">
            {{ avatarInitial(member) }}
          </span>
          <div class="pod-name-col">
            <div class="pod-name-line">
              <span class="pod-display-name">{{ member.display_name || member.email }}</span>

              <!-- 角色标签/下拉 -->
              <span v-if="member.is_owner" class="role-badge owner">所有者</span>
              <div v-else-if="vm.canManageMembers" class="role-pill-select" @click.stop>
                <button
                  type="button"
                  class="role-pill"
                  :class="member.role.toLowerCase()"
                  @click="toggleRoleMenu(member.id)"
                >
                  {{ vm.roleTag(member.role) }}
                  <ChevronDown class="pill-caret" />
                </button>
                <transition name="role-menu">
                  <div v-if="roleMenuOpenId === member.id" class="role-pill-menu">
                    <button
                      v-for="option in vm.memberRoleOptions"
                      :key="option.value"
                      type="button"
                      class="role-pill-menu-item"
                      :class="{ selected: option.value === member.role }"
                      @click="pickRole(member, option.value as 'DEVELOPER' | 'VIEWER')"
                    >
                      {{ option.label }}
                    </button>
                  </div>
                </transition>
              </div>
              <span v-else class="role-badge" :class="member.role.toLowerCase()">{{ vm.roleTag(member.role) }}</span>

              <span v-if="member.is_expert" class="expert-badge-compact">专家</span>
            </div>
            <span class="pod-email-line">{{ member.email }} · 加入于 {{ member.joined_at?.slice(0, 10) || '近期' }}</span>
          </div>
        </div>

        <!-- 中间：4 段微型刻度电量表 (无无异议装饰icon，纯净排版，浅蓝指示) -->
        <div class="mini-gauge-cluster">
          <div class="gauge-unit">
            <div class="gauge-meta">
              <span class="gauge-title">任务流</span>
              <span class="gauge-val">{{ taskCount(member.permissions) }}/5</span>
            </div>
            <div class="gauge-track">
              <div
                class="gauge-fill"
                :style="{ width: `${(taskCount(member.permissions) / 5) * 100}%` }"
              ></div>
            </div>
          </div>

          <div class="gauge-unit">
            <div class="gauge-meta">
              <span class="gauge-title">需求与资产</span>
              <span class="gauge-val">{{ assetCount(member.permissions) }}/5</span>
            </div>
            <div class="gauge-track">
              <div
                class="gauge-fill"
                :style="{ width: `${(assetCount(member.permissions) / 5) * 100}%` }"
              ></div>
            </div>
          </div>

          <div class="gauge-unit">
            <div class="gauge-meta">
              <span class="gauge-title">API Mock</span>
              <span class="gauge-val">{{ mockCount(member.permissions) }}/3</span>
            </div>
            <div class="gauge-track">
              <div
                class="gauge-fill"
                :style="{ width: `${(mockCount(member.permissions) / 3) * 100}%` }"
              ></div>
            </div>
          </div>

          <div class="gauge-unit">
            <div class="gauge-meta">
              <span class="gauge-title">治理</span>
              <span class="gauge-val">{{ govCount(member.permissions) }}/1</span>
            </div>
            <div class="gauge-track">
              <div
                class="gauge-fill"
                :style="{ width: `${govCount(member.permissions) * 100}%` }"
              ></div>
            </div>
          </div>
        </div>

        <!-- 右侧操作区 -->
        <div class="pod-actions-col">
          <button
            type="button"
            class="btn-subtle"
            title="微调该成员 14 项原子权限"
            @click="openPermissionDrawer(member)"
          >
            微调权限
          </button>

          <template v-if="vm.canManageMembers && !member.is_owner">
            <button
              type="button"
              class="btn-subtle"
              :class="{ 'is-active': member.is_expert }"
              :title="member.is_expert ? '取消专家认证' : '设为专家'"
              @click="quickToggleExpert(member)"
            >
              {{ member.is_expert ? '取消专家' : '标为专家' }}
            </button>
            <DeleteActionButton
              mode="icon"
              :title="$t('settings.members.remove_member')"
              :loading="vm.removingMemberId === member.id"
              @click="vm.askRemoveMember(member)"
            />
          </template>
          <span v-else-if="member.is_owner" class="pod-owner-readonly-badge">创建者</span>
        </div>
      </article>
    </div>

    <!-- 底部分页控制 -->
    <div v-if="vm.memberTotal > vm.MEMBER_PAGE_SIZE" class="member-pagination">
      <button class="btn-secondary" :disabled="vm.loadingMembers || vm.memberPage <= 1" @click="vm.prevMemberPage">
        {{ $t('settings.members.prev_page') }}
      </button>
      <span>{{ $t('settings.members.page_info', { page: vm.memberPage, total: vm.totalMemberPages }) }}</span>
      <button
        class="btn-secondary"
        :disabled="vm.loadingMembers || vm.memberPage >= vm.totalMemberPages"
        @click="vm.nextMemberPage"
      >
        {{ $t('settings.members.next_page') }}
      </button>
    </div>

    <!-- 权限微调侧滑抽屉 -->
    <SettingsMemberPermissionDrawer
      :visible="drawerVisible"
      :member="drawerEditingMember"
      :saving="vm.savingMemberId === drawerEditingMember?.id"
      :can-manage="vm.canManageMembers"
      @close="drawerVisible = false"
      @save="handleDrawerSave"
    />
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>
