<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementSummary } from '@/types/workspaceAssets'

const props = defineProps<{ requirement: RequirementSummary; userId?: string; enabled?: boolean; busy?: boolean }>()
const emit = defineEmits<{ claim: [clarify: boolean] }>()
const { t } = useI18n()
const visible = computed(() => props.enabled && props.userId && !props.requirement.child_count
  && !props.requirement.owner_id && !props.requirement.work_started
  && !['ARCHIVED', 'VERIFIED', 'PENDING_ACCEPTANCE'].includes(props.requirement.status))
</script>

<template>
  <el-button v-if="visible" size="small" :loading="busy" @click.stop="emit('claim', Boolean(requirement.clarification_reason))">
    {{ t(requirement.clarification_reason ? 'workspace_assets.delivery.claim_clarify' : 'workspace_assets.delivery.claim') }}
  </el-button>
</template>
