<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementAcceptanceAction, RequirementResultCheckAction, RequirementSummary } from '@/types/workspaceAssets'
import { canSubmitRequirementAcceptance, requirementStatusKey } from '@/utils/requirementStatus'

const props = defineProps<{ requirement: RequirementSummary; canManage: boolean; loading?: boolean; userId?: string }>()
const emit = defineEmits<{
  apply: [action: RequirementAcceptanceAction, reason?: string]
  resultCheck: [action: RequirementResultCheckAction, reason?: string]
}>()
const { t } = useI18n()
const action = shallowRef<RequirementAcceptanceAction | 'return_check'>()
const open = shallowRef(false)
const reason = shallowRef('')
const reasonRequired = computed(() => action.value === 'reject' || action.value === 'reopen' || action.value === 'return_check')
const actionTitle = computed(() => action.value === 'return_check'
  ? t('workspace_assets.delivery.return_check')
  : action.value ? t(`workspace_assets.requirements.acceptance.${action.value}`) : '')
const canSubmit = computed(() => canSubmitRequirementAcceptance(props.requirement.status))
const maySubmit = computed(() => props.canManage || (!!props.userId && props.requirement.owner_id === props.userId))
const mayDecide = computed(() => props.requirement.acceptor_id ? props.requirement.acceptor_id === props.userId : props.canManage)
const mayCheck = computed(() => props.requirement.reviewer_id ? props.requirement.reviewer_id === props.userId : props.canManage)

watch(() => props.requirement.id, () => { open.value = false })

function confirm(next: RequirementAcceptanceAction | 'return_check') {
  action.value = next
  reason.value = ''
  open.value = true
}

function submit() {
  if (!action.value || (reasonRequired.value && !reason.value.trim())) return
  const note = reason.value.trim() || undefined
  if (action.value === 'return_check') emit('resultCheck', 'return', note)
  else emit('apply', action.value, note)
  open.value = false
}
</script>

<template>
  <section id="requirement-acceptance" class="acceptance-panel" tabindex="-1">
    <header class="acceptance-heading">
      <h4>{{ t('workspace_assets.requirements.acceptance.title') }}</h4>
      <el-tag v-if="requirement.status === 'PENDING_ACCEPTANCE'" type="warning">
        {{ t(requirementStatusKey(requirement.status)) }}
      </el-tag>
    </header>
    <p v-if="requirement.acceptor_name" class="acceptance-help">
      {{ t('workspace_assets.delivery.acceptor') }} · {{ requirement.acceptor_name }}
    </p>
    <p v-if="requirement.acceptance_blocker === 'review_pending'" class="acceptance-help">
      {{ t('workspace_assets.delivery.review_pending') }}
    </p>
    <p v-else-if="requirement.acceptance_blocker && (canSubmit || requirement.status === 'PENDING_ACCEPTANCE')" class="acceptance-help">
      {{ t(`workspace_assets.requirements.acceptance.${requirement.acceptance_blocker}`) }}
    </p>
    <p v-else-if="canSubmit" class="acceptance-help">{{ t('workspace_assets.requirements.acceptance.submit_ready') }}</p>
    <div v-if="requirement.check_ready" class="acceptance-actions">
      <el-tag size="small" type="info">{{ t('workspace_assets.delivery.result_check_title') }}<template v-if="requirement.reviewer_name"> · {{ requirement.reviewer_name }}</template></el-tag>
      <el-button v-if="mayCheck" size="small" :loading="loading" @click="emit('resultCheck', 'complete')">
        {{ t('workspace_assets.delivery.check_result') }}
      </el-button>
      <el-button v-if="mayCheck" size="small" :disabled="loading" @click="confirm('return_check')">
        {{ t('workspace_assets.delivery.return_check') }}
      </el-button>
    </div>
    <div v-if="(canSubmit && maySubmit) || (!canSubmit && mayDecide)" class="acceptance-actions">
      <el-button v-if="canSubmit && maySubmit" size="small" type="primary" :disabled="loading || !!requirement.acceptance_blocker" @click="confirm('submit')">
        {{ t('workspace_assets.requirements.acceptance.submit') }}
      </el-button>
      <template v-else-if="requirement.status === 'PENDING_ACCEPTANCE'">
        <el-button size="small" type="success" :disabled="loading || !!requirement.acceptance_blocker" @click="confirm('approve')">
          {{ t('workspace_assets.requirements.acceptance.approve') }}
        </el-button>
        <el-button size="small" :disabled="loading" @click="confirm('reject')">
          {{ t('workspace_assets.requirements.acceptance.reject') }}
        </el-button>
      </template>
      <el-button v-else-if="requirement.status === 'VERIFIED'" size="small" :disabled="loading" @click="confirm('reopen')">
        {{ t('workspace_assets.requirements.acceptance.reopen') }}
      </el-button>
    </div>

    <el-dialog v-model="open" :title="actionTitle" width="min(480px, 92vw)" append-to-body>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item :label="t(action === 'return_check' ? 'workspace_assets.delivery.return_reason' : 'workspace_assets.requirements.acceptance.reason')" :required="reasonRequired">
          <el-input v-model="reason" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="loading || (reasonRequired && !reason.trim())" @click="submit">
          {{ t('common.confirm') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.acceptance-panel { display: grid; gap: 10px; scroll-margin-top: 24px; }
.acceptance-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.acceptance-heading h4 { margin: 0; font-size: 0.95rem; color: #1e3a8a; }
.acceptance-help { margin: 0; color: #52647c; font-size: 0.8125rem; }
.acceptance-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.acceptance-actions :deep(.el-button) { margin: 0; }
</style>
