<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'

type Member = { user_id: string; display_name: string }
const props = defineProps<{ workspaceId: string; initialOwner?: Member }>()
const ownerId = defineModel<string | null>({ required: true })
const { t } = useI18n()
const members = shallowRef<Member[]>([])
const remembered = shallowRef<Member | undefined>(props.initialOwner)
const loading = shallowRef(false)
const failed = shallowRef(false)
let request: AbortController | undefined

const options = computed(() => {
  const selected = remembered.value
  return selected && !members.value.some(member => member.user_id === selected.user_id)
    ? [selected, ...members.value]
    : members.value
})

async function search(keyword = '') {
  request?.abort()
  const controller = new AbortController()
  request = controller
  loading.value = true
  failed.value = false
  try {
    const { data } = await api.get<{ owner: Member | null; items: Member[] }>(
      `/workspaces/${props.workspaceId}/members`,
      { params: { keyword, page_size: 30 }, signal: controller.signal },
    )
    if (controller.signal.aborted) return
    members.value = [data.owner, ...data.items].filter((member): member is Member => Boolean(member))
  } catch {
    if (!controller.signal.aborted) {
      failed.value = true
      members.value = []
    }
  } finally {
    if (request === controller) loading.value = false
  }
}

function change(value?: string) {
  remembered.value = options.value.find(member => member.user_id === value)
  ownerId.value = value || null
}

onBeforeUnmount(() => request?.abort())
</script>

<template>
  <el-select
    :model-value="ownerId"
    :aria-label="t('workspace_assets.requirements.owner')"
    :placeholder="t('workspace_assets.requirements.owner_placeholder')"
    :remote-method="search"
    :loading="loading"
    clearable
    filterable
    remote
    @visible-change="$event && search()"
    @change="change"
  >
    <el-option v-for="member in options" :key="member.user_id" :label="member.display_name" :value="member.user_id" />
  </el-select>
  <small v-if="failed" role="alert">{{ t('settings.members.load_failed') }}</small>
</template>
