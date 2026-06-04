<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Dot } from 'lucide-vue-next'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <div class="file-tabs" v-if="vm.activeFilePath">
    <div class="file-tab active">
      <span>{{ vm.activeFilePath }}</span>
      <Dot v-if="vm.dirtyFiles.includes(vm.activeFilePath)" class="w-3 h-3" />
    </div>
  </div>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
