<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '@/stores/workspace'
import CaseCenterView from '@/components/case-center/CaseCenterView.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const wsStore = useWorkspaceStore()

const wsId = computed(() => String(route.params.wsId || ''))

const workspaceOptions = computed(() => [
  { label: t('knowledge.cases.workspace_all'), value: '' },
  ...wsStore.workspaces.map((ws) => ({ label: ws.name || String(ws.id), value: String(ws.id) })),
])

const selectedWsId = ref('')
const workspacesLoaded = ref(false)

watch(
  () => String(route.params.wsId || ''),
  (value) => {
    selectedWsId.value = value
  },
  { immediate: true },
)

// 工作区仅作为案例列表的过滤项，不作为主入口；通过路由写入 :wsId 便于深链与状态保持
watch(selectedWsId, (value) => {
  const next = String(value || '')
  if (next === wsId.value) return
  router.replace(next ? `/knowledge/cases/${next}` : '/knowledge/cases')
})

onMounted(async () => {
  try {
    await wsStore.fetchWorkspaces()
    // 先等工作区列表就绪再挂载案例列表；URL 未指定 wsId 时保持“全部工作区”，不自动选中某个工作区。
  } finally {
    workspacesLoaded.value = true
  }
})
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ t('knowledge.cases.title') }}</h2>
        <p class="mgmt-subtitle">{{ t('knowledge.cases.subtitle') }}</p>
      </div>
    </div>

    <CaseCenterView
      v-if="workspacesLoaded"
      v-model:workspace-id="selectedWsId"
      :workspace-options="workspaceOptions"
      embedded
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>