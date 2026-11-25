<script setup lang="ts">
import { computed, useTemplateRef, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { WORKSPACE_ASSET_CANVAS } from '@/router/workspaceAssetPresentation'
import CanvasOperationPanel from '@/components/workspace-canvas/CanvasOperationPanel.vue'
import WorkspaceAssetGraph from '@/components/workspace-canvas/WorkspaceAssetGraph.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const workspaceId = computed(() => String(route.params.wsId))
const panelTitle = computed(() => typeof route.meta.canvasTitle === 'string' ? t(route.meta.canvasTitle) : '')
const board = useTemplateRef<InstanceType<typeof WorkspaceAssetGraph>>('board')

function closePanel() {
  void router.replace({ name: WORKSPACE_ASSET_CANVAS, params: { wsId: workspaceId.value }, query: { quarter: route.query.quarter } })
}

watch(() => route.fullPath, () => { void board.value?.refresh() })
</script>

<template>
  <div class="asset-canvas-view">
    <WorkspaceAssetGraph ref="board" :key="`${workspaceId}:${auth.user?.id}`" :workspace-id="workspaceId">
      <template #workspace>
        <RouterView v-slot="{ Component }">
          <CanvasOperationPanel v-if="Component" :title="panelTitle" :wide="Boolean(route.meta.canvasWide)" @close="closePanel">
            <component :is="Component" />
          </CanvasOperationPanel>
        </RouterView>
      </template>
    </WorkspaceAssetGraph>
  </div>
</template>

<style scoped>
.asset-canvas-view { display: flex; flex: 1; min-height: 0; min-width: 0; padding: 10px; }
@media (max-width: 830px) { .asset-canvas-view { padding: 4px; } }
</style>
