<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Loader2, Trash2, Users, X } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import SettingsMembersAddModal from '@/components/settings/SettingsMembersAddModal.vue'
import SettingsMembersTable from '@/components/settings/SettingsMembersTable.vue'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const rawVm = props.vm
const vm = proxyRefs(rawVm)
</script>

<template>
  <section class="settings-section members-section">
    <div class="section-header">
      <div class="icon-circle">
        <Users class="w-6 h-6" />
      </div>
      <div class="section-title-group">
        <h2>{{ $t('settings.members.title') }}</h2>
        <p>{{ $t('settings.members.subtitle') }}</p>
      </div>
    </div>

    <div class="member-summary">
      <div class="summary-card">
        <span class="summary-label">{{ $t('settings.members.my_role') }}</span>
        <strong>{{ vm.roleTag(vm.myPermissionPayload?.role || 'VIEWER') }}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">{{ $t('settings.members.member_count') }}</span>
        <strong>{{ vm.totalMemberCount }}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">{{ $t('settings.members.delete_workspace_right') }}</span>
        <strong>{{ vm.myPermissionPayload?.can_delete_workspace ? $t('settings.members.yes') : $t('settings.members.no') }}</strong>
      </div>
    </div>

    <div v-if="vm.membersError" class="error-banner">{{ vm.membersError }}</div>

    <div v-if="!vm.canManageMembers" class="read-only-hint">
      {{ $t('settings.members.read_only_hint') }}
    </div>

    <SettingsMembersTable :vm="rawVm" />

    <Teleport to="body">
      <transition name="batch-bar">
        <div v-if="vm.selectedMemberCount > 0" class="member-batch-bar">
          <span class="batch-bar-count">{{ $t('settings.members.batch_selected', { count: vm.selectedMemberCount }) }}</span>
          <div class="batch-bar-role">
            <BaseSelect v-model="vm.batchRoleValue" :options="vm.memberRoleOptions" size="sm" />
          </div>
          <button class="btn-primary btn-compact" :disabled="vm.batchApplying" @click="vm.applyBatchRole">
            <Loader2 v-if="vm.batchApplying" class="w-4 h-4 spin" />
            {{ $t('settings.members.batch_apply_role') }}
          </button>
          <button class="btn-secondary btn-compact" :disabled="vm.batchApplying" @click="vm.applyBatchExpert(true)">
            {{ $t('settings.members.batch_mark_expert') }}
          </button>
          <button class="btn-secondary btn-compact" :disabled="vm.batchApplying" @click="vm.applyBatchExpert(false)">
            {{ $t('settings.members.batch_unmark_expert') }}
          </button>
          <button class="btn-compact-danger" :disabled="vm.batchRemoving" @click="vm.askRemoveSelectedMembers">
            <Trash2 class="w-4 h-4" />
            {{ $t('settings.members.batch_remove') }}
          </button>
          <button class="batch-bar-close" :title="$t('common.cancel')" @click="vm.clearMemberSelection">
            <X class="w-4 h-4" />
          </button>
        </div>
      </transition>
    </Teleport>

    <SettingsMembersAddModal :vm="rawVm" />
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>
