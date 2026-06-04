<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Loader2, Plus } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <aside class="member-left-rail">
    <div v-if="vm.canManageMembers" class="member-add-panel">
      <h3>{{ $t('settings.members.add_member') }}</h3>
      <div class="member-add-form">
        <input
          v-model="vm.addForm.user_email"
          class="input-field"
          type="email"
          :placeholder="$t('settings.members.email_placeholder')"
        >
        <BaseSelect
          v-model="vm.addForm.role"
          :options="vm.memberRoleOptions"
          size="lg"
        />
        <button class="btn-primary" :disabled="vm.addingMember || !vm.addForm.user_email.trim()" @click="vm.addMember">
          <Loader2 v-if="vm.addingMember" class="w-4 h-4 spin" />
          <Plus v-else class="w-4 h-4" />
          {{ $t('settings.members.add') }}
        </button>
      </div>

      <label class="expert-switch">
        <input v-model="vm.addForm.is_expert" type="checkbox">
        <span>{{ $t('settings.members.mark_as_expert') }}</span>
      </label>

      <div class="permission-grid add-grid">
        <label v-for="option in vm.permissionOptions" :key="option.key" class="permission-item">
          <input v-model="vm.addForm.permissions[option.key]" type="checkbox">
          <span>{{ option.label }}</span>
        </label>
      </div>
    </div>

    <p v-else class="read-only-hint">
      {{ $t('settings.members.read_only_hint') }}
    </p>
  </aside>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>


