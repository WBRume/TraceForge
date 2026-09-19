<script setup lang="ts">
import { proxyRefs, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, ChevronRight, Brain, FileText, GitFork } from 'lucide-vue-next'
import DocReviewWorkbench from '@/components/doc-review/DocReviewWorkbench.vue'
import SuperpowersDocsPanel from '@/components/chat/SuperpowersDocsPanel.vue'
import { useDiagnosisDocs } from '@/composables/useDiagnosisDocs'
import DiagnosisDocsPanel from './DiagnosisDocsPanel.vue'
import DiagnosisCodePathPanel from './DiagnosisCodePathPanel.vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * Spec 文档抽屉（三段式容器）：侧把手控制 1-3 级宽度、标签页切换与面板编排。
 * 研发态任务 → 需求文档 / 计划文档；问题定位任务 → 诊断文档 / 代码路径
 * （诊断数据在本组件自治加载，随抽屉展开拉取、随会话切换失效）。
 */
const props = defineProps<{
  vm: ChatViewVm
}>()

const { t } = useI18n()

const diagDocs = proxyRefs(useDiagnosisDocs({
  wsId: () => String(props.vm.route.params.wsId || ''),
  taskId: () => String(props.vm.currentTask?.id || ''),
}))

// 打开诊断抽屉时加载文档与代码路径
watch(
  () => [props.vm.isDiagnosisTask, props.vm.specDrawerLevel],
  () => {
    if (props.vm.isDiagnosisTask && props.vm.specDrawerLevel > 0) {
      void diagDocs.loadDocs()
      void diagDocs.loadCodePath()
    }
  },
)
</script>

<template>
  <aside
    v-if="props.vm.currentTask && (props.vm.isSpecDrawerAvailable || props.vm.isDiagnosisTask || props.vm.isPdfSpec)"
    class="spec-sidebar glass-panel"
    :class="{
      'is-open': props.vm.isSpecPanelOpen,
      'level-1': props.vm.specDrawerLevel === 1,
      'level-2': props.vm.specDrawerLevel === 2,
      'level-3': props.vm.specDrawerLevel === 3,
    }"
  >
    <!-- Simplified Side Handles -->
    <div class="spec-side-handles">
      <div class="side-handle-group">
        <button
          class="side-handle-btn"
          :disabled="props.vm.specDrawerLevel === 3"
          @click="props.vm.handleExpandDrawer"
          :title="t('common.expand')"
        >
          <ChevronLeft :size="20" />
        </button>

        <div class="handle-divider"></div>

        <button
          class="side-handle-btn"
          @click="props.vm.handleCollapseDrawer"
          :title="props.vm.specDrawerLevel === 1 ? t('common.close') : t('common.collapse')"
        >
          <ChevronRight :size="20" />
        </button>
      </div>
    </div>

    <div class="spec-body" v-show="props.vm.isSpecPanelOpen && props.vm.currentTask">
      <!-- 问题定位任务：诊断文档 / 代码路径 -->
      <div v-if="props.vm.isDiagnosisTask" class="spec-tabbar">
        <button
          class="tab-item"
          :class="{ active: props.vm.specDrawerTab === 'diag_docs' }"
          @click="props.vm.specDrawerTab = 'diag_docs'"
        >
          <FileText :size="14" />
          <span>{{ t('diagnosis.docs_tab') }}</span>
        </button>
        <button
          class="tab-item"
          :class="{ active: props.vm.specDrawerTab === 'diag_code' }"
          @click="props.vm.specDrawerTab = 'diag_code'"
        >
          <GitFork :size="14" />
          <span>{{ t('diagnosis.code_path_tab') }}</span>
        </button>
      </div>
      <!-- 研发态任务：需求文档 / 计划文档 -->
      <div v-else class="spec-tabbar">
        <button
          class="tab-item"
          :class="{ active: props.vm.specDrawerTab === 'spec_doc' }"
          @click="props.vm.specDrawerTab = 'spec_doc'"
        >
          <div v-show="props.vm.specDrawerTab === 'spec_doc' && props.vm.currentTaskHasSpec" class="pulse-dot-inline"></div>
          <FileText :size="14" />
          <span>{{ t('chat.spec_drawer_tab_requirement') }}</span>
        </button>
        <button
          class="tab-item"
          :class="{ active: props.vm.specDrawerTab === 'superpowers_docs' }"
          @click="props.vm.specDrawerTab = 'superpowers_docs'"
        >
          <div v-show="props.vm.specDrawerTab === 'superpowers_docs'" class="pulse-dot-inline"></div>
          <Brain :size="14" />
          <span>{{ t('chat.spec_drawer_tab_superpowers') }}</span>
        </button>
      </div>
      <div class="spec-tab-panels">
        <!-- 问题定位：诊断文档面板 -->
        <div
          v-if="props.vm.isDiagnosisTask"
          class="spec-tab-panel"
          v-show="props.vm.specDrawerTab === 'diag_docs'"
        >
          <DiagnosisDocsPanel :model="diagDocs" />
        </div>

        <!-- 问题定位：代码路径面板 -->
        <div
          v-if="props.vm.isDiagnosisTask"
          class="spec-tab-panel"
          v-show="props.vm.specDrawerTab === 'diag_code'"
        >
          <DiagnosisCodePathPanel :model="diagDocs" />
        </div>

        <!-- 研发态：需求文档 -->
        <div
          v-if="!props.vm.isDiagnosisTask && props.vm.currentTaskHasSpec"
          class="spec-tab-panel"
          v-show="props.vm.specDrawerTab === 'spec_doc'"
        >
          <DocReviewWorkbench
            :ws-id="String(props.vm.route.params.wsId || '')"
            :task-id="props.vm.currentTask.id"
            :initial-asset-id="props.vm.activeInitialSpecAssetId || undefined"
            :readonly="true"
            compact
          />
        </div>
        <!-- 研发态：计划文档 -->
        <div
          v-if="!props.vm.isDiagnosisTask"
          class="spec-tab-panel"
          v-show="props.vm.specDrawerTab === 'superpowers_docs'"
        >
          <SuperpowersDocsPanel
            :ws-id="String(props.vm.route.params.wsId || '')"
            :task-id="props.vm.currentTask.id"
            :readonly="!props.vm.canEditSuperpowersDocs"
            :visible="props.vm.isSpecPanelOpen && props.vm.specDrawerTab === 'superpowers_docs'"
          />
        </div>
      </div>
    </div>
    <div class="spec-empty" v-show="props.vm.isSpecPanelOpen && !props.vm.currentTask">
      {{ t('chat.spec_drawer_empty') }}
    </div>
  </aside>
</template>

<style scoped>
.spec-sidebar {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 0;
  opacity: 0;
  pointer-events: none;
  transform: translateX(14px);
  border-radius: 0;
  border: none;
  border-left: 1px solid rgba(2, 132, 199, 0.12);
  background: rgba(255, 255, 255, 0.96);
  display: flex;
  flex-direction: column;
  overflow: visible; /* allow side handles to hang out */
  box-shadow: -8px 0 24px rgba(15, 23, 42, 0.1);
  transition: width 0.28s ease, opacity 0.28s ease, transform 0.28s ease;
  z-index: 40;
}

.spec-sidebar.is-open {
  opacity: 1;
  pointer-events: auto;
  transform: translateX(0);
}

.spec-sidebar.is-open.level-1 {
  width: clamp(680px, 48vw, 860px);
}

.spec-sidebar.is-open.level-2 {
  width: clamp(860px, 72vw, 1280px);
}

.spec-sidebar.is-open.level-3 {
  width: calc(100% - 250px);
}

.spec-side-handles {
  position: absolute;
  left: -40px;
  top: 50%;
  transform: translateY(-50%);
  width: 40px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(14, 165, 233, 0.12);
  border-right: none;
  border-radius: 12px 0 0 12px;
  display: flex;
  flex-direction: column;
  padding: 12px 0;
  box-shadow: -8px 2px 24px rgba(15, 23, 42, 0.05);
  z-index: 41;
}


.spec-tabbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  margin: 12px 16px;
  background: #f1f5f9;
  border-radius: 12px;
  border: 1px solid rgba(14, 165, 233, 0.08);
  flex-shrink: 0;
}

.spec-tabbar .tab-item {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  background: transparent;
  border: 1px solid transparent;
  color: #64748B;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.spec-tabbar .tab-item:hover {
  background: rgba(255, 255, 255, 0.6);
  color: #0ea5e9;
}

.spec-tabbar .tab-item:active {
  transform: scale(0.97);
}

.spec-tabbar .tab-item.active {
  background: white;
  color: #0ea5e9;
  border-color: rgba(14, 165, 233, 0.12);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.pulse-dot-inline {
  width: 6px;
  height: 6px;
  background: #0ea5e9;
  border-radius: 50%;
  margin-right: -2px;
}


@keyframes pulse {
  0% { transform: scale(1); opacity: 1; }
  100% { transform: scale(3); opacity: 0; }
}

.side-handle-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
}

.handle-divider {
  width: 24px;
  height: 1px;
  background: rgba(148, 163, 184, 0.2);
  margin: 4px 0;
}

.side-handle-btn {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  border: 1px solid transparent;
  background: transparent;
  color: #64748B;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  margin: 0 auto;
}

.side-handle-btn:hover {
  background: #f1f5f9;
  color: #0ea5e9;
  border-color: rgba(14, 165, 233, 0.2);
}

.side-handle-btn.active {
  background: #eff6ff;
  color: #0ea5e9;
  border-color: rgba(14, 165, 233, 0.4);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.15);
}

.side-handle-btn.close-btn:hover {
  background: #fef2f2;
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.2);
}

.pulse-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 8px;
  height: 8px;
  background-color: #0ea5e9;
  border-radius: 50%;
}

.pulse-dot::after {
  content: '';
  position: absolute;
  width: 100%;
  height: 100%;
  background: #0ea5e9;
  border-radius: 50%;
  animation: pulse 2s infinite;
  left: 0;
  top: 0;
}

.spec-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0;
  background: #fff;
}

.spec-tab-panels {
  flex: 1;
  min-height: 0;
  display: flex;
}

.spec-tab-panel {
  flex: 1;
  min-height: 0;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.spec-empty {
  padding: 14px;
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.spec-body :deep(.doc-review-workbench) {
  height: 100%;
}

.spec-body :deep(.superpowers-docs-panel) {
  height: 100%;
}

@media (max-width: 1600px) {
  .spec-sidebar.is-open.level-1 {
    width: min(70vw, 860px);
  }

  .spec-sidebar.is-open.level-2 {
    width: min(82vw, 1180px);
  }
}

@media (max-width: 1200px) {
  .spec-sidebar.is-open.level-1 {
    width: min(82vw, 900px);
  }

  .spec-sidebar.is-open.level-2 {
    width: min(90vw, 1040px);
  }

  .spec-sidebar.is-open.level-3 {
    width: 100%;
  }
}
</style>
