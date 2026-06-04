<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Loader2 } from 'lucide-vue-next'
import { useTaskDetailSections } from '@/composables/useTaskDetailSections'
import { useTaskDetailAssets } from '@/composables/useTaskDetailAssets'
import WorkbenchSummaryBar from '@/components/diff/WorkbenchSummaryBar.vue'
import DeltaFileNav from '@/components/diff/DeltaFileNav.vue'
import HumanPatchCompare from '@/components/diff/HumanPatchCompare.vue'
import DeltaRegionPanel from '@/components/diff/DeltaRegionPanel.vue'
import DecisionCreateDialog from '@/components/workspace-assets/task-detail/DecisionCreateDialog.vue'
import DecisionPopover from '@/components/diff/DecisionPopover.vue'
import type { WorkbenchDelta, DeltaRegion, DeltaLineRef, DecisionMutationPayload } from '@/types/workspaceAssets'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const wsId = computed(() => route.params.wsId as string)
const taskId = computed(() => route.params.taskId as string)
const deltaId = computed(() => route.params.deltaId as string)

const { loadWorkbenchDelta } = useTaskDetailSections()
const { createDecision, updateHumanDelta } = useTaskDetailAssets()

const delta = ref<WorkbenchDelta | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const selectedFilePath = ref<string | null>(null)
const selectedRegion = ref<DeltaRegion | null>(null)

const diffViewer = ref<InstanceType<typeof HumanPatchCompare> | null>(null)

const decisionDialogOpen = ref(false)
const decisionDialogLineRefs = ref<DeltaLineRef[]>([])

const popoverVisible = ref(false)
const popoverFilePath = ref('')
const popoverLineStart = ref(0)
const popoverLineEnd = ref(0)
const popoverSelectedText = ref('')
const popoverAnchorTop = ref(0)
const popoverAnchorLeft = ref(0)

const humanPatchSource = computed(() => {
  const hp = delta.value?.human_patch
  if (!hp) return null
  return {
    source_type: hp.source_type,
    source_ref: hp.source_id,
    source_uri: null as string | null,
    source_label: hp.source_label,
  }
})

async function loadData() {
  loading.value = true
  error.value = null
  try {
    delta.value = await loadWorkbenchDelta(wsId.value, taskId.value, deltaId.value)
  } catch (e: any) {
    error.value = e?.message ?? 'Failed to load delta'
  } finally {
    loading.value = false
  }
}

function onSelectFile(filePath: string) {
  selectedFilePath.value = filePath
  diffViewer.value?.scrollToFile(filePath)
  const regions = delta.value?.delta_regions.filter(r => r.file_path === filePath) ?? []
  selectedRegion.value = regions[0] ?? null
}

function onRangeSelect(payload: { filePath: string; lineStart: number; lineEnd: number; source: string; selectedText: string }) {
  popoverFilePath.value = payload.filePath
  popoverLineStart.value = payload.lineStart
  popoverLineEnd.value = payload.lineEnd
  popoverSelectedText.value = payload.selectedText
  popoverAnchorTop.value = 120
  popoverAnchorLeft.value = Math.max(20, (window.innerWidth - 340) / 2)
  popoverVisible.value = true
}

function onCreateDecision(payload: { region: DeltaRegion; deltaId: string }) {
  const refs: DeltaLineRef[] = []
  if (payload.region.human_line_start) {
    refs.push({
      file_path: payload.region.file_path,
      line_start: payload.region.human_line_start,
      line_end: payload.region.human_line_end ?? payload.region.human_line_start,
    })
  } else if (payload.region.ai_line_start) {
    refs.push({
      file_path: payload.region.file_path,
      line_start: payload.region.ai_line_start,
      line_end: payload.region.ai_line_end ?? payload.region.ai_line_start,
    })
  }
  decisionDialogLineRefs.value = refs
  decisionDialogOpen.value = true
}

async function onPopoverSubmit(payload: DecisionMutationPayload) {
  try {
    await createDecision(wsId.value, taskId.value, payload)
    popoverVisible.value = false
    await loadData()
  } catch (e: any) {
    error.value = e?.message ?? 'Failed to create decision'
  }
}

async function onSubmitDecision(payload: DecisionMutationPayload) {
  try {
    await createDecision(wsId.value, taskId.value, payload)
    decisionDialogOpen.value = false
    await loadData()
  } catch (e: any) {
    error.value = e?.message ?? 'Failed to create decision'
  }
}

async function onUpdatePromote(dId: string, value: boolean) {
  try {
    await updateHumanDelta(wsId.value, taskId.value, dId, { promote_candidate: value })
    if (delta.value) {
      delta.value.promote_candidate = value
    }
  } catch (e: any) {
    error.value = e?.message ?? 'Failed to update promote status'
  }
}

function goBack() {
  router.push({ name: 'workspaceAssetTaskDetail', params: { wsId: wsId.value, taskId: taskId.value }, query: { section: 'humanDelta' } })
}

onMounted(loadData)
</script>

<template>
  <div class="delta-workbench">
    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <Loader2 :size="24" class="spinner" />
      <span>{{ t('workspace_assets.task_detail.workbench.delta_workbench.loading') }}</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button @click="loadData">{{ t('common.retry') }}</button>
    </div>

    <!-- Workbench -->
    <template v-else-if="delta">
      <!-- Top bar with back button -->
      <div class="workbench-topbar">
        <button class="back-btn" @click="goBack">
          <ArrowLeft :size="16" />
          {{ t('workspace_assets.task_detail.workbench.delta_workbench.back') }}
        </button>
      </div>

      <!-- Summary bar -->
      <WorkbenchSummaryBar :delta="delta" />

      <!-- Main workbench area -->
      <div class="workbench-body">
        <!-- Left: File navigation -->
        <aside class="workbench-sidebar">
          <DeltaFileNav
            :file-diffs="delta.file_diffs"
            :delta-regions="delta.delta_regions"
            :selected-file-path="selectedFilePath"
            @select-file="onSelectFile"
          />
        </aside>

        <!-- Center: Diff viewer -->
        <main class="workbench-diff">
          <HumanPatchCompare
            ref="diffViewer"
            :file-diffs="delta.file_diffs"
            :delta-regions="delta.delta_regions"
            :selected-file-path="selectedFilePath"
            @range-select="onRangeSelect"
          />
        </main>

        <!-- Right: Region detail panel -->
        <aside class="workbench-detail">
          <DeltaRegionPanel
            :region="selectedRegion"
            :delta-id="delta.id"
            :human-patch-source="humanPatchSource"
            :promote-candidate="delta.promote_candidate"
            @create-decision="onCreateDecision"
            @update-promote="onUpdatePromote"
          />
        </aside>

        <!-- Decision popover (positioned inside workbench-body) -->
        <DecisionPopover
          :visible="popoverVisible"
          :file-path="popoverFilePath"
          :line-start="popoverLineStart"
          :line-end="popoverLineEnd"
          :selected-text="popoverSelectedText"
          :delta-id="deltaId"
          :anchor-top="popoverAnchorTop"
          :anchor-left="popoverAnchorLeft"
          @submit="onPopoverSubmit"
          @close="popoverVisible = false"
        />
      </div>

      <!-- Decision create dialog -->
      <DecisionCreateDialog
        :open="decisionDialogOpen"
        :delta-id="deltaId"
        :line-refs="decisionDialogLineRefs"
        @submit="onSubmitDecision"
        @close="decisionDialogOpen = false"
      />
    </template>
  </div>
</template>

<style scoped>
.delta-workbench {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--color-background, #fff);
}

.loading-state, .error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--color-text-secondary, #6b7280);
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.workbench-topbar {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--color-border, #e5e7eb);
  flex-shrink: 0;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  background: none;
  font-size: 13px;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  border-radius: 6px;
}

.back-btn:hover {
  background: var(--color-background-hover, #f3f4f6);
  color: var(--color-text-primary, #111827);
}

.workbench-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.workbench-sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--color-border, #e5e7eb);
  overflow-y: auto;
}

.workbench-diff {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.workbench-detail {
  width: 280px;
  flex-shrink: 0;
  border-left: 1px solid var(--color-border, #e5e7eb);
  overflow-y: auto;
}
</style>
