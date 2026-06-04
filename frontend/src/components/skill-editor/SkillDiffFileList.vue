<script setup lang="ts">
import { proxyRefs } from 'vue'
import { FileDiff } from 'lucide-vue-next'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <section class="diff-file-panel glass-panel">
    <div class="diff-file-header">
      <div class="diff-file-title">
        <FileDiff class="w-4 h-4" />
        <span>{{ $t('skills.editor.diff_files') }}</span>
      </div>
    </div>

    <div v-if="vm.diffFiles.length === 0" class="tree-state">
      {{ $t('skills.editor.diff_file_empty') }}
    </div>

    <div v-else class="diff-file-list custom-scrollbar">
      <button
        v-for="item in vm.diffFiles"
        :key="`${item.status}:${item.path}`"
        class="diff-file-row"
        :class="{ active: vm.activeDiffFilePath === item.path }"
        @click="vm.loadFileDiff(item.path)"
      >
        <span class="diff-status">{{ item.status }}</span>
        <span class="diff-path">{{ item.path }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
