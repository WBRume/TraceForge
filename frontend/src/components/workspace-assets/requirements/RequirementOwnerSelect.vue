<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import BaseSelect from '@/components/BaseSelect.vue'
import type { MemberWorkload } from '@/types/workload'
import { countsFor } from '../workload/workloadCounts'

type Member = { user_id: string; display_name: string }
const props = defineProps<{
  workspaceId: string
  initialOwner?: Member
  label?: string
  workloads?: readonly MemberWorkload[]
}>()
const ownerId = defineModel<string | null>({ required: true })
const { t } = useI18n()
const members = shallowRef<Member[]>([])
const remembered = shallowRef<Member | undefined>(props.initialOwner)
const failed = shallowRef(false)
let request: AbortController | undefined
let timer: ReturnType<typeof setTimeout> | undefined
const byId = computed(() => new Map(props.workloads?.map(member => [member.user_id, member])))

const options = computed(() => {
  const selected = remembered.value
  const choices = selected && !members.value.some(member => member.user_id === selected.user_id)
    ? [selected, ...members.value] : members.value
  return [
    { label: t('workspace_assets.requirements.owner_unassigned'), value: null },
    ...choices.map(member => {
      const workload = byId.value.get(member.user_id)
      return {
        label: member.display_name,
        value: member.user_id,
        detail: workload ? t('workspace_assets.workload.option_summary', countsFor(workload)) : undefined,
      }
    }),
  ]
})

async function search(keyword = '') {
  request?.abort()
  const controller = new AbortController()
  request = controller
  failed.value = false
  try {
    const { data } = await api.get<{ owner: Member | null; items: Member[] }>(
      `/workspaces/${props.workspaceId}/members`,
      { params: { keyword, page_size: 30 }, signal: controller.signal },
    )
    if (controller.signal.aborted) return
    members.value = [...new Map([data.owner, ...data.items].filter((member): member is Member => member !== null
      && (!keyword || member !== data.owner || member.display_name.toLocaleLowerCase().includes(keyword.toLocaleLowerCase())))
      .map(member => [member.user_id, member])).values()]
  } catch {
    if (!controller.signal.aborted) {
      failed.value = true
      members.value = []
    }
  }
}

function scheduleSearch(keyword: string) {
  request?.abort()
  clearTimeout(timer)
  timer = setTimeout(() => void search(keyword.trim()), 150)
}

function change(value: string | null) {
  const option = options.value.find(item => item.value === value)
  remembered.value = value && option ? { user_id: value, display_name: option.label } : undefined
  ownerId.value = value
}

onBeforeUnmount(() => { clearTimeout(timer); request?.abort() })
</script>

<template>
  <BaseSelect
    :model-value="ownerId"
    :aria-label="label || t('workspace_assets.requirements.owner')"
    :placeholder="t('workspace_assets.requirements.owner_placeholder')"
    :search-placeholder="t('workspace_assets.workload.search')"
    :options="options"
    searchable remote-search
    @open="scheduleSearch('')"
    @search="scheduleSearch"
    @update:model-value="change"
  />
  <small v-if="failed" role="alert">{{ t('settings.members.load_failed') }}</small>
</template>
