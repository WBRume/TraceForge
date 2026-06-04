<script setup lang="ts">
import { proxyRefs } from 'vue'
import { ArrowLeft, Eye, FileCode2, GitBranch, Loader2, Pencil, RefreshCw, Save, ShieldCheck } from 'lucide-vue-next'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <nav class="navbar glass-panel sticky-header">
    <div class="nav-left">
      <button class="icon-btn-ghost" @click="vm.navigateBack" :title="$t('skills.editor.back_to_skills')">
        <ArrowLeft class="w-5 h-5" />
      </button>
      <div class="v-divider"></div>
      <div class="page-info">
        <div class="badge-tag sm">
          <span class="pulse-dot"></span>
          {{ vm.form.dimension === 'GLOBAL' ? $t('skills.editor.dimension_global') : $t('skills.editor.dimension_workspace') }}
        </div>
        <h1 class="title-gradient">{{ vm.pageTitle }}</h1>
      </div>
      <div v-if="vm.isEdit" class="editor-tabs" role="tablist" aria-label="Skill editor sections">
        <button
          type="button"
          class="editor-tab"
          :class="{ active: vm.activeEditorTab === 'files' }"
          :aria-selected="vm.activeEditorTab === 'files'"
          @click="vm.goEditorFilesTab"
        >
          <FileCode2 class="w-4 h-4" />
          <span>{{ $t('skills.editor.tab_files') }}</span>
        </button>
        <button
          type="button"
          class="editor-tab"
          :class="{ active: vm.activeEditorTab === 'analysis' }"
          :aria-selected="vm.activeEditorTab === 'analysis'"
          @click="vm.goEditorAnalysisTab"
        >
          <ShieldCheck class="w-4 h-4" />
          <span>{{ $t('skills.editor.tab_analysis') }}</span>
        </button>
      </div>
    </div>

    <div class="nav-actions">
      <div v-if="vm.isUnpublishedSkill" class="publish-status-badge draft">
        {{ $t('skills.list.unpublished') }}
      </div>

      <div
        v-if="vm.isOfficialSourceSkill"
        class="publish-status-badge official"
        :title="vm.sourceRepoUrl || undefined"
      >
        {{ $t('skills.editor.official_source_badge') }}
      </div>

      <div v-if="vm.isReadOnly" class="readonly-badge">
        {{ vm.readOnlyHintText }}
      </div>

      <button
        v-if="vm.isOfficialSourceSkill && vm.canManage"
        class="btn-outline-sm"
        :disabled="!vm.canSyncOfficialSource"
        @click="vm.syncOfficialSource"
      >
        <Loader2 v-if="vm.sourceSyncing" class="w-4 h-4 animate-spin" />
        <RefreshCw v-else class="w-4 h-4" />
        <span>{{ vm.sourceSyncing ? $t('skills.editor.syncing_official_source') : $t('skills.editor.sync_official_source') }}</span>
      </button>

      <button v-if="vm.canSwitchToEdit" class="btn-outline-sm" @click="vm.showSwitchToEditConfirm = true">
        <Pencil class="w-4 h-4" />
        <span>{{ $t('skills.editor.switch_to_edit') }}</span>
      </button>

      <button
        v-if="vm.isEdit && !vm.isReadOnly && vm.canManage"
        class="btn-outline-sm"
        @click="vm.switchToReadOnlyMode"
      >
        <Eye class="w-4 h-4" />
        <span>{{ $t('skills.editor.switch_to_readonly') }}</span>
      </button>

      <button
        v-if="!vm.isReadOnly"
        class="btn-primary-sm"
        :disabled="!vm.canSave"
        @click="vm.saveSkill"
      >
        <Loader2 v-if="vm.saving" class="w-4 h-4 animate-spin" />
        <Save v-else class="w-4 h-4" />
        <span>
          {{ vm.saving ? $t('skills.editor.saving') : $t('skills.editor.save') }}
        </span>
      </button>

      <button
        v-if="vm.isEdit && !vm.isReadOnly"
        class="btn-outline-sm"
        :disabled="!vm.canPublish"
        @click="vm.openPublishConfirm"
      >
        <Loader2 v-if="vm.publishing" class="w-4 h-4 animate-spin" />
        <GitBranch v-else class="w-4 h-4" />
        <span>{{ vm.publishing ? $t('skills.editor.publishing') : $t('skills.editor.publish') }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
<style scoped>
.publish-status-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.18rem 0.65rem;
  font-size: 0.72rem;
  font-weight: 600;
}

.publish-status-badge.draft {
  color: #92400e;
  background: #fef3c7;
  border: 1px solid #fcd34d;
}

.publish-status-badge.official {
  color: #075985;
  background: #e0f2fe;
  border: 1px solid #7dd3fc;
}

.editor-tabs {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem;
  border: 1px solid #dbeafe;
  border-radius: var(--radius-lg);
  background: rgba(248, 250, 252, 0.8);
}

.editor-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  min-height: 34px;
  border: none;
  border-radius: var(--radius-md);
  padding: 0.35rem 0.7rem;
  color: #64748b;
  background: transparent;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.editor-tab:hover {
  color: #0f172a;
  background: #fff;
}

.editor-tab.active {
  color: #075985;
  background: linear-gradient(135deg, #e0f2fe 0%, #ecfeff 100%);
  box-shadow: 0 1px 3px rgba(14, 165, 233, 0.18);
}

@media (max-width: 1024px) {
  .nav-left {
    flex-wrap: wrap;
  }
}
</style>
