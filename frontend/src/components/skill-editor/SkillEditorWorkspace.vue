<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import { GitCompare, Info, MousePointer2 } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import SkillEditorMonacoStage from '@/components/skill-editor/SkillEditorMonacoStage.vue'
import SkillDiffFileList from '@/components/skill-editor/SkillDiffFileList.vue'
import SkillFileTreePanel from '@/components/skill-editor/SkillFileTreePanel.vue'
import type { SkillEditorViewModel, SkillFileNode } from '@/composables/useSkillEditorViewModel'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const rawVm = props.vm
const vm = proxyRefs(rawVm)

const countFiles = (nodes: SkillFileNode[]): number => {
  let count = 0
  nodes.forEach((node) => {
    if (node.node_type === 'file') {
      count += 1
      return
    }
    count += countFiles(node.children || [])
  })
  return count
}

const showFileTree = computed(() => {
  const fileCount = countFiles(vm.fileTree || [])
  return !vm.isReadOnly || fileCount > 1
})
</script>

<template>
  <section class="editor-section">
    <div class="editor-container glass-panel">
      <div class="editor-toolbar">
        <div class="toolbar-left">
          <div v-if="vm.isDiffMode" class="diff-info">
            <GitCompare class="w-4 h-4 text-primary-500" />
            <span>
              {{ vm.activeDiffFilePath || '-' }} · v{{ vm.diffPayload.fromVersionNo }} -> v{{ vm.diffPayload.toVersionNo }}
            </span>
          </div>
          <div v-else class="editor-mode-badge">
            {{ vm.activeFilePath || vm.form.entryFilePath }}
          </div>
        </div>
      </div>

      <div class="side-card editor-meta-form">
        <div class="side-form">
          <div class="meta-flex-form">
            <div class="meta-row">
              <div class="side-form-group select-group">
                <label>{{ $t('skills.editor.dimension') }}</label>
                <BaseSelect
                  v-model="vm.form.dimension"
                  :options="vm.dimensionOptions"
                  :disabled="vm.isReadOnly"
                />
              </div>
              <div v-if="vm.form.dimension === 'WORKSPACE'" class="side-form-group workspace-group" :class="{ 'has-error': vm.formErrors.workspaceId }">
                <label>{{ $t('skills.editor.target_workspace') }} <span class="required-mark">*</span></label>
                <BaseSelect
                  v-model="vm.form.workspaceId"
                  :options="vm.workspaceOptions"
                  :disabled="vm.isReadOnly"
                />
              </div>
            </div>
            
            <div class="meta-row">
              <div class="side-form-group name-group" :class="{ 'has-error': vm.formErrors.name }">
                <label>{{ $t('skills.editor.name') }} <span class="required-mark">*</span></label>
                <input
                  v-model="vm.form.name"
                  class="side-input"
                  :disabled="vm.isReadOnly"
                  :placeholder="$t('skills.editor.name_placeholder')"
                >
              </div>
              <div class="side-form-group entry-group">
                <label>{{ $t('skills.editor.entry_file') }}</label>
                <input v-model="vm.form.entryFilePath" class="side-input mono-input" :disabled="vm.isReadOnly">
              </div>
            </div>
            <div class="meta-row">
              <div class="side-form-group desc-group">
                <label>{{ $t('skills.editor.description') }}</label>
                <input
                  v-model="vm.form.description"
                  class="side-input"
                  :disabled="vm.isReadOnly"
                  :placeholder="$t('skills.editor.description_placeholder')"
                >
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="editor-body-grid" :class="{ 'single-file': !showFileTree }">
        <SkillFileTreePanel v-if="showFileTree" :vm="rawVm" />

        <div class="editor-main-panel">
          <SkillDiffFileList v-if="vm.isDiffMode" :vm="rawVm" />
          <SkillEditorMonacoStage :vm="rawVm" />
        </div>
      </div>

      <div class="editor-footer">
        <div v-if="!vm.isDiffMode && vm.selectedRange" class="selection-badge">
          <MousePointer2 class="w-3.5 h-3.5" />
          <span>{{ $t('skills.editor.selection_info', { start: vm.selectedRange.line_start, end: vm.selectedRange.line_end }) }}</span>
          <button class="close-btn-sm" @click="vm.clearSelectedRange()">&times;</button>
        </div>
        <p v-else class="hint-text">
          <Info class="w-3.5 h-3.5" />
          {{ vm.isDiffMode ? $t('skills.editor.diff_mode_active_hint') : $t('skills.editor.selection_hint') }}
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>

<style scoped>
.meta-flex-form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: end;
}

.meta-row > .side-form-group {
  flex: 1 1 auto;
}

.meta-row > .name-group {
  flex: 1.5 1 180px;
}

.meta-row > .select-group {
  flex: 1 1 120px;
}

.meta-row > .workspace-group {
  flex: 2 1 200px;
}

.meta-row > .entry-group {
  flex: 1.5 1 200px;
}

.meta-row > .desc-group {
  flex: 1 1 100%;
}
</style>
