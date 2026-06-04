<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Loader2, Save } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <section class="member-right-rail">
    <div class="member-list-panel">
      <div class="member-list-head">
        <div class="member-list-title-group">
          <h3>{{ $t('settings.members.title') }}</h3>
          <p>{{ $t('settings.members.member_count') }}: {{ vm.totalMemberCount }}</p>
        </div>
        <span class="member-list-chip">{{ $t('settings.members.page_info', { page: vm.memberPage, total: vm.totalMemberPages }) }}</span>
      </div>

      <div class="member-query">
        <input
          v-model="vm.memberKeywordInput"
          class="input-field"
          type="text"
          :placeholder="$t('settings.members.search_placeholder')"
          @keyup.enter="vm.runMemberSearch"
        >
        <button class="btn-secondary" :disabled="vm.loadingMembers" @click="vm.runMemberSearch">
          {{ $t('settings.members.search') }}
        </button>
        <button
          v-if="vm.memberKeywordQuery"
          class="btn-secondary"
          :disabled="vm.loadingMembers"
          @click="vm.clearMemberSearch"
        >
          {{ $t('settings.members.clear_search') }}
        </button>
      </div>

      <div v-if="vm.loadingMembers" class="member-loading">
        <Loader2 class="w-5 h-5 spin text-primary" />
        <span>{{ $t('settings.members.loading') }}</span>
      </div>

      <div v-else-if="!vm.ownerMember && vm.members.length === 0" class="member-empty">
        {{ $t('settings.members.empty') }}
      </div>

      <div v-else class="member-content">
        <div v-if="vm.ownerMember" class="owner-spotlight">
          <div class="owner-spotlight-label">{{ $t('settings.members.role_owner') }}</div>
          <article class="member-card owner">
            <div class="member-head">
              <div>
                <h4>{{ vm.ownerMember.display_name || vm.ownerMember.email }}</h4>
                <p>{{ vm.ownerMember.email }}</p>
              </div>
              <div class="member-head-right">
                <span class="role-badge owner">{{ vm.roleTag(vm.ownerMember.role) }}</span>
                <span v-if="vm.ownerMember.is_expert" class="expert-badge">{{ $t('settings.members.expert_badge') }}</span>
                <button class="permission-toggle-btn" @click="vm.togglePermissionExpanded(vm.ownerMember.id)">
                  {{ vm.isPermissionExpanded(vm.ownerMember.id) ? $t('settings.members.hide_permissions') : $t('settings.members.show_permissions') }}
                </button>
              </div>
            </div>
            <div class="permission-summary">
              {{ $t('settings.members.permissions_summary', { enabled: vm.enabledPermissionCount(vm.ownerMember), total: vm.permissionOptionCount }) }}
            </div>
            <div v-if="vm.isPermissionExpanded(vm.ownerMember.id)" class="permission-grid">
              <div
                v-for="option in vm.permissionOptions"
                :key="`${vm.ownerMember.id}-${option.key}`"
                class="permission-readonly"
                :class="{ enabled: vm.ownerMember.permissions[option.key] }"
              >
                {{ option.label }}
              </div>
            </div>
          </article>
        </div>

        <div v-if="vm.members.length === 0" class="member-empty member-empty-inline">
          {{ $t('settings.members.empty') }}
        </div>

        <div v-else class="member-list">
          <article
            v-for="member in vm.members"
            :key="member.id"
            class="member-card"
          >
            <div class="member-head">
              <div>
                <h4>{{ member.display_name || member.email }}</h4>
                <p>{{ member.email }}</p>
              </div>
              <div class="member-head-right">
                <span class="role-badge" :class="member.role.toLowerCase()">{{ vm.roleTag(member.role) }}</span>
                <span v-if="member.is_expert || vm.memberDrafts[member.id]?.is_expert" class="expert-badge">{{ $t('settings.members.expert_badge') }}</span>
                <button class="permission-toggle-btn" @click="vm.togglePermissionExpanded(member.id)">
                  {{ vm.isPermissionExpanded(member.id) ? $t('settings.members.hide_permissions') : $t('settings.members.show_permissions') }}
                </button>
              </div>
            </div>

            <div v-if="vm.canManageMembers && !member.is_owner" class="member-edit-row">
              <BaseSelect
                v-model="vm.memberDrafts[member.id].role"
                :options="vm.memberRoleOptions"
                size="lg"
                @update:model-value="vm.applyDraftRoleDefaults(member.id)"
              />
              <label class="expert-switch inline">
                <input v-model="vm.memberDrafts[member.id].is_expert" type="checkbox">
                <span>{{ $t('settings.members.mark_as_expert') }}</span>
              </label>
            </div>

            <div class="permission-summary">
              {{ $t('settings.members.permissions_summary', { enabled: vm.enabledPermissionCount(member), total: vm.permissionOptionCount }) }}
            </div>

            <div v-if="vm.isPermissionExpanded(member.id)" class="permission-grid">
              <template v-if="vm.canManageMembers && !member.is_owner">
                <label v-for="option in vm.permissionOptions" :key="`${member.id}-${option.key}`" class="permission-item">
                  <input v-model="vm.memberDrafts[member.id].permissions[option.key]" type="checkbox">
                  <span>{{ option.label }}</span>
                </label>
              </template>

              <template v-else>
                <div
                  v-for="option in vm.permissionOptions"
                  :key="`${member.id}-${option.key}`"
                  class="permission-readonly"
                  :class="{ enabled: member.permissions[option.key] }"
                >
                  {{ option.label }}
                </div>
              </template>
            </div>

            <div v-if="vm.canManageMembers && !member.is_owner" class="member-actions">
              <button class="btn-secondary" :disabled="vm.savingMemberId === member.id" @click="vm.saveMember(member)">
                <Loader2 v-if="vm.savingMemberId === member.id" class="w-4 h-4 spin" />
                <Save v-else class="w-4 h-4" />
                {{ $t('settings.members.save_member') }}
              </button>
              <DeleteActionButton
                mode="mini"
                :label="$t('settings.members.remove_member')"
                :loading="vm.removingMemberId === member.id"
                @click="vm.askRemoveMember(member)"
              />
            </div>
          </article>
        </div>
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
    </div>
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>


