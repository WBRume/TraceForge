<script setup lang="ts">
import { proxyRefs, shallowRef, watch, onBeforeUnmount } from 'vue'
import { ChevronRight, ChevronLeft, Info, Loader2, Maximize2, Minimize2 } from 'lucide-vue-next'
import { VueMonacoEditor, VueMonacoDiffEditor } from '@guolao/vue-monaco-editor'
import SkillEditorSidebar from './SkillEditorSidebar.vue'
import SkillDiffFileList from './SkillDiffFileList.vue'
import SkillReadonlyFileTree from './SkillReadonlyFileTree.vue'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'
import type * as Monaco from 'monaco-editor'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const vm = proxyRefs(props.vm)

// Workaround for @guolao/vue-monaco-editor diff widget crash on unmount
const diffWidgetRef = shallowRef<Monaco.editor.IStandaloneDiffEditor | null>(null)
const handleDiffMount = (editor: Monaco.editor.IStandaloneDiffEditor) => {
  diffWidgetRef.value = editor
}

watch(() => vm.rightDrawerTab, (newTab, oldTab) => {
  if (oldTab === 'diff' && newTab !== 'diff') {
    if (diffWidgetRef.value) {
      diffWidgetRef.value.setModel(null)
    }
  }
})
watch(() => vm.rightDrawerLevel, (newLevel, oldLevel) => {
  if (oldLevel >= 2 && newLevel < 2) {
    if (diffWidgetRef.value) {
      diffWidgetRef.value.setModel(null)
    }
  }
})

onBeforeUnmount(() => {
  if (diffWidgetRef.value) {
    diffWidgetRef.value.setModel(null)
  }
})
</script>

<template>
  <aside
    class="spec-sidebar glass-panel"
    :class="{
      'is-open': vm.isRightDrawerOpen,
      'level-1': vm.rightDrawerLevel === 1,
      'level-2': vm.rightDrawerLevel === 2,
      'level-3': vm.rightDrawerLevel === 3
    }"
  >
    <div class="spec-side-handles">
      <div class="side-handle-group">
        <button
          v-if="vm.isRightDrawerOpen && vm.rightDrawerLevel >= 2"
          class="side-handle-btn"
          @click="vm.toggleDrawerFullWidth"
          :title="vm.rightDrawerLevel === 3 ? $t('common.restore') : $t('common.maximize')"
        >
          <Minimize2 v-if="vm.rightDrawerLevel === 3" :size="18" />
          <Maximize2 v-else :size="18" />
        </button>

        <button
          v-if="vm.isRightDrawerOpen"
          class="side-handle-btn"
          @click="vm.toggleRightDrawer"
          :title="$t('common.close')"
        >
          <ChevronRight :size="20" />
        </button>
        <button
          v-else
          class="side-handle-btn"
          @click="vm.toggleRightDrawer"
          :title="$t('common.open')"
        >
          <ChevronLeft :size="20" />
        </button>
      </div>
    </div>

    <div class="spec-body" v-show="vm.isRightDrawerOpen">
      <div class="drawer-panel-extended">
        <!-- Always render the sidebar, its width is fixed or flex-shrink: 0 -->
        <div class="drawer-sidebar-col custom-scrollbar">
          <SkillEditorSidebar :vm="props.vm" />
        </div>
        
        <!-- Only render the viewer column if level >= 2 -->
        <div v-if="vm.rightDrawerLevel >= 2" class="drawer-viewer-col">
          <!-- Diff Mode -->
          <template v-if="vm.rightDrawerTab === 'diff'">
            <div class="diff-viewer-layout">
              <SkillDiffFileList :vm="props.vm" class="diff-list-col" />
              <div class="diff-editor-col">
                <template v-if="vm.diffPayload.loaded">
                  <VueMonacoDiffEditor
                    v-if="!vm.diffPayload.isBinary"
                    :original="vm.diffPayload.original"
                    :modified="vm.diffPayload.modified"
                    :language="vm.drawerActiveLanguage"
                    theme="vs"
                    :options="vm.diffEditorOptions"
                    width="100%"
                    height="100%"
                    @mount="handleDiffMount"
                  />
                  <div v-else class="binary-placeholder glass-panel">
                    <Info class="w-12 h-12 text-slate-300 mx-auto mb-3" />
                    <p>{{ $t('skills.editor.binary_diff_unsupported') }}</p>
                  </div>
                </template>
                <div v-else-if="!vm.diffLoading" class="diff-loading-placeholder glass-panel">
                  <Loader2 class="w-8 h-8 spin text-primary" />
                  <p>{{ $t('skills.editor.loading_diff') }}</p>
                </div>
              </div>
            </div>
          </template>

          <!-- History Mode -->
          <template v-if="vm.rightDrawerTab === 'history'">
            <div class="diff-viewer-layout">
              <SkillReadonlyFileTree 
                :nodes="vm.drawerFileTree" 
                :active-path="vm.drawerActiveFilePath"
                :loading="vm.drawerTreeLoading"
                @select="vm.openDrawerFile" 
                class="diff-list-col" 
              />
              <div class="diff-editor-col">
                <template v-if="vm.drawerActiveFilePath">
                  <VueMonacoEditor
                    v-if="!vm.drawerIsBinary"
                    v-model:value="vm.drawerFileContent"
                    :language="vm.drawerActiveLanguage"
                    theme="vs"
                    :options="{ ...vm.editorOptions, readOnly: true }"
                    width="100%"
                    height="100%"
                  />
                  <div v-else class="binary-placeholder glass-panel">
                    <Info class="w-12 h-12 text-slate-300 mx-auto mb-3" />
                  </div>
                </template>
                <div v-else class="diff-loading-placeholder glass-panel">
                  <p>{{ $t('skills.editor.empty_state_desc') }}</p>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.spec-sidebar {
  position: absolute;
  top: 76px;
  bottom: 0;
  right: -340px; /* level 1 width */
  width: 340px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 250, 252, 0.98) 100%);
  border-left: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: -10px 0 25px -5px rgba(0, 0, 0, 0.1), -5px 0 10px -5px rgba(0, 0, 0, 0.04);
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  flex-direction: column;
  z-index: 20;
}
.spec-sidebar.is-open {
  right: 0;
}
.spec-sidebar.level-2 {
  width: 65vw;
}
.spec-sidebar.level-3 {
  width: calc(100vw - 64px);
}

.spec-side-handles {
  position: absolute;
  left: -48px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-right: none;
  border-radius: 12px 0 0 12px;
  box-shadow: -4px 0 12px rgba(0, 0, 0, 0.05);
  overflow: hidden;
  z-index: 10;
}

.side-handle-btn {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.side-handle-btn:not(:disabled):hover {
  color: var(--color-primary-600);
  background: rgba(14, 165, 233, 0.05);
}

.spec-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drawer-panel-simple {
  flex: 1;
  padding: 1rem;
  overflow-y: auto;
}

.drawer-panel-extended {
  flex: 1;
  display: flex;
  height: 100%;
  overflow: hidden;
}

.drawer-sidebar-col {
  flex: 0 0 340px;
  padding: 1rem;
  overflow-y: auto;
  border-right: 1px solid rgba(0, 0, 0, 0.08);
}

.spec-sidebar.level-1 .drawer-sidebar-col {
  flex: 1;
  border-right: none;
}

.drawer-viewer-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-surface-white);
}

.diff-viewer-layout {
  display: flex;
  height: 100%;
}

.diff-list-col {
  width: 250px;
  border-right: 1px solid var(--color-border);
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.diff-editor-col {
  flex: 1;
  position: relative;
  display: flex;
  flex-direction: column;
}

.binary-placeholder, .diff-loading-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
}
</style>
