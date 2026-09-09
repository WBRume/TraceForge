<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Loader2, Save, Search } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import type { PermissionKey } from '@/utils/settingsPermissions'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)

type MemberRow = {
  id: string
  email: string
  display_name: string
  role: string
  is_owner: boolean
  is_expert: boolean
  permissions: Record<string, boolean>
}

const avatarInitial = (member: MemberRow) => (
  (member.display_name || member.email).trim().charAt(0).toUpperCase() || '?'
)

const permissionOn = (member: MemberRow, key: PermissionKey) => Boolean(member.permissions?.[key])

const colCount = () => (vm.canManageMembers ? 6 : 5)
</script>

<template>
  <section class="member-console-panel">
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

    <div class="member-table-wrap">
      <table class="member-table">
        <colgroup>
          <col v-if="vm.canManageMembers" class="colc-check">
          <col class="colc-member">
          <col class="colc-role">
          <col class="colc-expert">
          <col class="colc-perms">
          <col class="colc-actions">
        </colgroup>
        <thead>
          <tr>
            <th v-if="vm.canManageMembers" class="col-check">
              <input
                type="checkbox"
                class="member-check"
                :checked="vm.allFilteredSelected"
                :disabled="vm.selectableFilteredCount === 0"
                @change="vm.toggleSelectAllFiltered"
              >
            </th>
            <th>{{ $t('settings.members.col_member') }}</th>
            <th class="col-role">{{ $t('settings.members.col_role') }}</th>
            <th class="col-expert">{{ $t('settings.members.col_expert') }}</th>
            <th>{{ $t('settings.members.col_permissions') }}</th>
            <th class="col-actions"></th>
          </tr>
        </thead>
        <tbody v-if="vm.loadingMembers">
          <tr>
            <td :colspan="colCount()">
              <div class="member-loading">
                <Loader2 class="w-5 h-5 spin text-primary" />
                <span>{{ $t('settings.members.loading') }}</span>
              </div>
            </td>
          </tr>
        </tbody>
        <tbody v-else>
          <template v-for="member in vm.filteredConsoleMembers" :key="member.id">
            <tr class="member-row" :class="{ 'is-owner': member.is_owner }">
              <td v-if="vm.canManageMembers" class="col-check">
                <input
                  v-if="!member.is_owner"
                  type="checkbox"
                  class="member-check"
                  :checked="vm.isMemberSelected(member.id)"
                  @change="vm.toggleMemberSelected(member.id)"
                >
              </td>
              <td>
                <div class="member-identity">
                  <span class="member-avatar" :class="{ owner: member.is_owner }">{{ avatarInitial(member) }}</span>
                  <div class="member-name">
                    <b>{{ member.display_name || member.email }}</b>
                    <small>{{ member.email }}</small>
                  </div>
                </div>
              </td>
              <td class="col-role">
                <span v-if="member.is_owner" class="role-badge owner">{{ vm.roleTag(member.role) }}</span>
                <div v-else-if="vm.canManageMembers" class="role-select-wrap">
                  <BaseSelect
                    v-model="vm.memberDrafts[member.id].role"
                    :options="vm.memberRoleOptions"
                    size="sm"
                    @update:model-value="vm.applyDraftRoleDefaults(member.id)"
                  />
                </div>
                <span v-else class="role-badge" :class="member.role.toLowerCase()">{{ vm.roleTag(member.role) }}</span>
              </td>
              <td class="col-expert">
                <span v-if="member.is_owner" class="expert-badge">{{ $t('settings.members.expert_badge') }}</span>
                <button
                  v-else-if="vm.canManageMembers"
                  type="button"
                  class="member-toggle"
                  :class="{ on: vm.memberDrafts[member.id]?.is_expert }"
                  :aria-pressed="Boolean(vm.memberDrafts[member.id]?.is_expert)"
                  @click="vm.toggleDraftExpert(member.id)"
                ></button>
                <span v-else-if="member.is_expert" class="expert-badge">{{ $t('settings.members.expert_badge') }}</span>
                <span v-else class="member-readonly-tag">—</span>
              </td>
              <td>
                <div class="heat-cell">
                  <span class="heat-dots">
                    <span
                      v-for="option in vm.permissionOptions"
                      :key="option.key"
                      class="heat-dot"
                      :class="{ on: permissionOn(member, option.key) }"
                    ></span>
                  </span>
                  <span class="heat-count">{{ vm.enabledPermissionCount(member) }}/{{ vm.permissionOptionCount }}</span>
                  <button class="permission-toggle-btn" @click="vm.togglePermissionExpanded(member.id)">
                    {{ vm.isPermissionExpanded(member.id) ? $t('settings.members.hide_permissions') : $t('settings.members.show_permissions') }}
                  </button>
                </div>
              </td>
              <td class="col-actions">
                <div v-if="vm.canManageMembers && !member.is_owner" class="member-row-actions">
                  <button
                    class="btn-secondary btn-compact"
                    :disabled="vm.savingMemberId === member.id"
                    @click="vm.saveMember(member)"
                  >
                    <Loader2 v-if="vm.savingMemberId === member.id" class="w-4 h-4 spin" />
                    <Save v-else class="w-4 h-4" />
                    {{ $t('settings.members.save_member') }}
                  </button>
                  <DeleteActionButton
                    mode="icon"
                    :title="$t('settings.members.remove_member')"
                    :loading="vm.removingMemberId === member.id"
                    @click="vm.askRemoveMember(member)"
                  />
                </div>
                <span v-else-if="member.is_owner" class="member-readonly-tag">{{ $t('settings.members.readonly_tag') }}</span>
              </td>
            </tr>
            <tr v-if="vm.isPermissionExpanded(member.id)" class="member-detail-row">
              <td :colspan="colCount()">
                <div v-if="vm.canManageMembers && !member.is_owner" class="permission-grid">
                  <label
                    v-for="option in vm.permissionOptions"
                    :key="`${member.id}-${option.key}`"
                    class="permission-item"
                  >
                    <input v-model="vm.memberDrafts[member.id].permissions[option.key]" type="checkbox">
                    <span>{{ option.label }}</span>
                  </label>
                </div>
                <div v-else class="permission-grid">
                  <div
                    v-for="option in vm.permissionOptions"
                    :key="`${member.id}-${option.key}`"
                    class="permission-readonly"
                    :class="{ enabled: permissionOn(member, option.key) }"
                  >
                    {{ option.label }}
                  </div>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="!vm.filteredConsoleMembers.length">
            <td :colspan="colCount()">
              <div class="member-empty member-empty-inline">{{ $t('settings.members.empty') }}</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

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
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>
