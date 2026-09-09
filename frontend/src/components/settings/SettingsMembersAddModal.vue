<script setup lang="ts">
import { proxyRefs, ref } from 'vue'
import { AlertCircle, CheckCircle2, Copy, Link2, Loader2, Mail, Plus, Trash2, X } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)

const showCustomPermissions = ref(false)
const copiedToken = ref('')

const stateText = (state: string) => {
  if (state === 'duplicate') return props.vm.t('settings.members.batch_state_duplicate')
  if (state === 'invalid') return props.vm.t('settings.members.batch_state_invalid')
  if (state === 'repeat') return props.vm.t('settings.members.batch_state_repeat')
  return ''
}

const validDaysOptions = [
  { value: 7, label: props.vm.t('settings.members.invite_valid_7') },
  { value: 30, label: props.vm.t('settings.members.invite_valid_30') },
  { value: 90, label: props.vm.t('settings.members.invite_valid_90') },
  { value: 0, label: props.vm.t('settings.members.invite_valid_forever') },
]

const maxUsesOptions = [
  { value: 5, label: props.vm.t('settings.members.invite_uses_5') },
  { value: 20, label: props.vm.t('settings.members.invite_uses_20') },
  { value: 0, label: props.vm.t('settings.members.invite_uses_unlimited') },
]

const statusText = (status: string) => props.vm.t(`settings.members.invite_status_${status}`)

const formatDate = (value: string | null) => (
  value ? new Date(value).toLocaleDateString() : ''
)

const usageText = (link: { used_count: number; max_uses: number | null }) => (
  link.max_uses
    ? props.vm.t('settings.members.invite_used_with_limit', { used: link.used_count, limit: link.max_uses })
    : props.vm.t('settings.members.invite_used_no_limit', { used: link.used_count })
)

const copyLink = async (token: string) => {
  await props.vm.copyInviteLinkUrl(token)
  copiedToken.value = token
  setTimeout(() => {
    if (copiedToken.value === token) copiedToken.value = ''
  }, 2000)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="vm.showAddModal" class="modal-overlay" @click.self="vm.closeAddModal">
      <div class="member-modal">
        <header class="member-modal-head">
          <div>
            <h3>{{ $t('settings.members.batch_add_title') }}</h3>
            <p>{{ $t('settings.members.batch_add_subtitle') }}</p>
          </div>
          <button class="modal-close" :disabled="vm.batchAddRunning" @click="vm.closeAddModal">
            <X class="w-4 h-4" />
          </button>
        </header>

        <div v-if="!vm.batchAddDone" class="modal-tabs">
          <button
            type="button"
            class="modal-tab"
            :class="{ active: vm.addModalTab === 'email' }"
            @click="vm.addModalTab = 'email'"
          >
            <Mail class="w-4 h-4" />
            {{ $t('settings.members.invite_tab_email') }}
          </button>
          <button
            type="button"
            class="modal-tab"
            :class="{ active: vm.addModalTab === 'link' }"
            @click="vm.addModalTab = 'link'"
          >
            <Link2 class="w-4 h-4" />
            {{ $t('settings.members.invite_tab_link') }}
          </button>
        </div>

        <!-- 结果视图 -->
        <div v-if="vm.batchAddDone" class="member-modal-body">
          <h4 class="batch-result-title">{{ $t('settings.members.batch_add_done_title') }}</h4>
          <div class="batch-results">
            <div
              v-for="result in vm.batchAddResults"
              :key="result.email"
              class="batch-result-row"
              :class="result.ok ? 'ok' : 'fail'"
            >
              <CheckCircle2 v-if="result.ok" class="w-4 h-4" />
              <AlertCircle v-else class="w-4 h-4" />
              <span class="batch-result-email">{{ result.email }}</span>
              <span class="batch-result-state">{{ result.ok ? $t('settings.members.batch_result_ok') : (result.reason || $t('settings.members.batch_result_fail')) }}</span>
            </div>
          </div>
        </div>

        <!-- 邮箱邀请 -->
        <div v-else-if="vm.addModalTab === 'email'" class="member-modal-body">
          <div>
            <label class="modal-field-label">{{ $t('settings.members.batch_emails_label') }}</label>
            <textarea
              v-model="vm.batchAddInput"
              class="member-email-textarea"
              rows="4"
              :placeholder="$t('settings.members.email_placeholder')"
            ></textarea>
            <div v-if="vm.batchAddEmails.length" class="parse-chips">
              <span
                v-for="item in vm.batchAddEmails"
                :key="`${item.email}-${item.state}`"
                class="parse-chip"
                :class="item.state"
              >
                {{ item.email }}
                <em v-if="item.state !== 'ok'" class="parse-chip-note">{{ stateText(item.state) }}</em>
              </span>
            </div>
            <p v-else class="parse-hint">{{ $t('settings.members.batch_parse_hint') }}</p>
          </div>

          <div class="modal-row">
            <div class="modal-field">
              <label class="modal-field-label">{{ $t('settings.members.batch_role_label') }}</label>
              <BaseSelect v-model="vm.batchAddRole" :options="vm.memberRoleOptions" />
            </div>
            <label class="expert-switch modal-expert">
              <input v-model="vm.batchAddExpert" type="checkbox">
              <span>{{ $t('settings.members.mark_as_expert') }}</span>
            </label>
          </div>

          <div>
            <button type="button" class="permission-toggle-btn" @click="showCustomPermissions = !showCustomPermissions">
              {{ showCustomPermissions ? $t('settings.members.hide_permissions') : $t('settings.members.custom_permissions') }}
              · {{ $t('settings.members.permissions_summary', { enabled: vm.batchAddEnabledCount, total: vm.permissionOptionCount }) }}
            </button>
            <div v-if="showCustomPermissions" class="permission-grid modal-perm-grid">
              <label
                v-for="option in vm.permissionOptions"
                :key="option.key"
                class="permission-item"
              >
                <input v-model="vm.batchAddPermissions[option.key]" type="checkbox">
                <span>{{ option.label }}</span>
              </label>
            </div>
          </div>
        </div>

        <!-- 链接邀请 -->
        <div v-else class="member-modal-body">
          <div v-if="vm.inviteLinkError" class="error-banner modal-error">{{ vm.inviteLinkError }}</div>

          <div class="link-create-card">
            <div class="modal-row">
              <div class="modal-field">
                <label class="modal-field-label">{{ $t('settings.members.batch_role_label') }}</label>
                <BaseSelect v-model="vm.inviteLinkForm.role" :options="vm.memberRoleOptions" />
              </div>
              <div class="modal-field">
                <label class="modal-field-label">{{ $t('settings.members.invite_link_valid_days') }}</label>
                <BaseSelect v-model="vm.inviteLinkForm.valid_days" :options="validDaysOptions" />
              </div>
              <div class="modal-field">
                <label class="modal-field-label">{{ $t('settings.members.invite_max_uses') }}</label>
                <BaseSelect v-model="vm.inviteLinkForm.max_uses" :options="maxUsesOptions" />
              </div>
            </div>
            <label class="expert-switch modal-expert">
              <input v-model="vm.inviteLinkForm.is_expert" type="checkbox">
              <span>{{ $t('settings.members.mark_as_expert') }}</span>
            </label>
            <div class="link-create-foot">
              <span class="modal-foot-note">{{ $t('settings.members.invite_link_hint') }}</span>
              <button class="btn-primary" :disabled="vm.inviteLinkCreating" @click="vm.createInviteLink">
                <Loader2 v-if="vm.inviteLinkCreating" class="w-4 h-4 spin" />
                <Link2 v-else class="w-4 h-4" />
                {{ vm.inviteLinkCreating ? $t('settings.members.invite_link_creating') : $t('settings.members.invite_link_create') }}
              </button>
            </div>
          </div>

          <div v-if="vm.inviteLinkJustCreated" class="link-result-box">
            <span class="link-result-url">{{ vm.buildInviteJoinUrl(vm.inviteLinkJustCreated.token) }}</span>
            <button class="btn-secondary link-copy-btn" @click="copyLink(vm.inviteLinkJustCreated.token)">
              <Copy class="w-4 h-4" />
              {{ copiedToken === vm.inviteLinkJustCreated.token ? $t('settings.members.invite_link_copied') : $t('settings.members.invite_link_copy') }}
            </button>
          </div>

          <div class="link-list-section">
            <div class="modal-field-label">
              {{ $t('settings.members.invite_link_list') }}
              <span v-if="vm.inviteLinks.length">（{{ vm.inviteLinks.length }}）</span>
            </div>
            <div v-if="vm.inviteLinksLoading" class="member-loading link-loading">
              <Loader2 class="w-4 h-4 spin text-primary" />
            </div>
            <div v-else-if="!vm.inviteLinks.length" class="link-empty">
              {{ $t('settings.members.invite_link_empty') }}
            </div>
            <div v-else class="link-list">
              <div v-for="link in vm.inviteLinks" :key="link.id" class="link-item">
                <div class="link-item-main">
                  <span class="role-badge" :class="link.role.toLowerCase()">{{ vm.roleTag(link.role) }}</span>
                  <span v-if="link.is_expert" class="expert-badge">{{ $t('settings.members.expert_badge') }}</span>
                  <span class="link-status" :class="`is-${link.status.toLowerCase()}`">{{ statusText(link.status) }}</span>
                  <span class="link-meta">{{ usageText(link) }}</span>
                </div>
                <div class="link-item-url" :title="vm.buildInviteJoinUrl(link.token)">
                  {{ vm.buildInviteJoinUrl(link.token) }}
                </div>
                <div class="link-item-foot">
                  <span class="link-meta">
                    {{ link.expires_at ? $t('settings.members.invite_expires_until', { date: formatDate(link.expires_at) }) : $t('settings.members.invite_no_expiry') }}
                  </span>
                  <div class="link-item-acts">
                    <button class="permission-toggle-btn" @click="copyLink(link.token)">
                      <Copy class="w-4 h-4" />
                      {{ copiedToken === link.token ? $t('settings.members.invite_link_copied') : $t('settings.members.invite_link_copy') }}
                    </button>
                    <button
                      v-if="link.status === 'ACTIVE'"
                      class="btn-compact-danger"
                      :disabled="vm.revokingLinkId === link.id"
                      @click="vm.revokeInviteLink(link)"
                    >
                      <Loader2 v-if="vm.revokingLinkId === link.id" class="w-4 h-4 spin" />
                      <Trash2 v-else class="w-4 h-4" />
                      {{ $t('settings.members.invite_link_revoke') }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <footer class="member-modal-foot">
          <span v-if="!vm.batchAddDone && vm.addModalTab === 'email'" class="modal-foot-note">
            {{ $t('settings.members.batch_add_summary', { ok: vm.batchAddValidEmails.length, blocked: vm.batchAddBlockedCount }) }}
          </span>
          <button class="btn-secondary" :disabled="vm.batchAddRunning" @click="vm.batchAddDone ? vm.resetBatchAdd() : vm.closeAddModal()">
            {{ vm.batchAddDone ? $t('settings.members.batch_add_more') : $t('common.cancel') }}
          </button>
          <button
            v-if="!vm.batchAddDone && vm.addModalTab === 'email'"
            class="btn-primary"
            :disabled="vm.batchAddRunning || vm.batchAddValidEmails.length === 0"
            @click="vm.runBatchAdd"
          >
            <Loader2 v-if="vm.batchAddRunning" class="w-4 h-4 spin" />
            <Plus v-else class="w-4 h-4" />
            {{ vm.batchAddRunning ? $t('settings.members.batch_add_running') : $t('settings.members.batch_add_run', { count: vm.batchAddValidEmails.length }) }}
          </button>
          <button v-if="vm.batchAddDone" class="btn-primary" @click="vm.closeAddModal">
            {{ $t('settings.members.batch_add_close') }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>
