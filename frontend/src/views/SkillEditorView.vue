<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Loader2, Star, X } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import SkillAnalysisPanel from '@/components/skill-editor/SkillAnalysisPanel.vue'
import SkillEditorHeader from '@/components/skill-editor/SkillEditorHeader.vue'
import SkillEditorRightDrawer from '@/components/skill-editor/SkillEditorRightDrawer.vue'
import SkillEditorSidebar from '@/components/skill-editor/SkillEditorSidebar.vue'
import SkillEditorWorkspace from '@/components/skill-editor/SkillEditorWorkspace.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import { useSkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

const rawVm = useSkillEditorViewModel()
const vm = proxyRefs(rawVm)
</script>


<template>
  <div class="editor-page">
    <SkillEditorHeader :vm="rawVm" />

    <main class="main-content">
      <div v-if="vm.loading" class="state-row">
        <Loader2 class="w-5 h-5 animate-spin text-primary" />
        <span>{{ $t('skills.editor.loading') }}</span>
      </div>

      <template v-else>
        <SkillAnalysisPanel
          v-if="vm.isAnalysisTabActive"
          :vm="rawVm"
          class="analysis-route-panel"
        />
        <div v-else class="layout-grid" :class="{ 'readonly-layout': vm.isSidebarLayout }">
          <SkillEditorWorkspace :vm="rawVm" />
          <SkillEditorSidebar v-if="vm.isSidebarLayout" :vm="rawVm" />
        </div>
        <SkillEditorRightDrawer v-if="vm.isEdit && !vm.isSidebarLayout && !vm.isAnalysisTabActive" :vm="rawVm" />
      </template>
    </main>

    <ConfirmActionModal
      :show="vm.showSwitchToEditConfirm"
      :title="$t('skills.editor.switch_to_edit')"
      :message="$t('skills.editor.enter_edit_confirm')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="primary"
      @cancel="vm.showSwitchToEditConfirm = false"
      @confirm="vm.confirmSwitchToEditMode"
    />

    <ConfirmActionModal
      :show="vm.showPublishConfirm"
      :title="$t('skills.editor.publish_dialog_title')"
      :message="$t('skills.editor.publish_dialog_message')"
      :description="$t('skills.editor.publish_dialog_version_hint')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('skills.editor.publish_dialog_confirm')"
      tone="primary"
      :loading="vm.publishing"
      @cancel="vm.cancelPublishConfirm"
      @confirm="vm.confirmPublish"
    >
      <template #content>
        <label class="commit-note-label">{{ $t('skills.editor.change_note') }}</label>
        <textarea
          v-model="vm.pendingPublishNote"
          class="commit-note-input"
          :placeholder="$t('skills.editor.change_note_placeholder')"
          rows="4"
        />
      </template>
    </ConfirmActionModal>

    <ConfirmActionModal
      :show="vm.showCreateNodeModal"
      :title="vm.createNodeDialogTitle"
      :message="$t('skills.editor.create_node_dialog_message')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('skills.editor.create_node_confirm')"
      tone="primary"
      :loading="vm.creatingNode"
      @cancel="vm.cancelCreateNode"
      @confirm="vm.confirmCreateNode"
    >
      <template #content>
        <label class="commit-note-label">{{ $t('skills.editor.create_node_parent') }}</label>
        <BaseSelect v-model="vm.createNodeParentPath" :options="vm.directoryOptions" />
        <label class="commit-note-label mt-3">{{ $t('skills.editor.create_node_name') }}</label>
        <input
          v-model="vm.createNodeName"
          class="create-node-input"
          :placeholder="vm.createNodeNamePlaceholder"
          @keydown.enter.prevent="vm.confirmCreateNode"
        >
      </template>
    </ConfirmActionModal>

    <ConfirmActionModal
      :show="vm.showRenameNodeModal"
      :title="vm.renameNodeDialogTitle"
      :message="$t('skills.editor.rename_node_dialog_message', { path: vm.renameNodeSourcePath || '-' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('skills.editor.rename_node_confirm')"
      tone="primary"
      :loading="vm.renamingNode"
      @cancel="vm.cancelRenameNode"
      @confirm="vm.confirmRenameNode"
    >
      <template #content>
        <label class="commit-note-label">{{ $t('skills.editor.rename_node_name') }}</label>
        <input
          v-model="vm.renameNodeName"
          class="create-node-input"
          :placeholder="vm.renameNodeNamePlaceholder"
          @keydown.enter.prevent="vm.confirmRenameNode"
        >
      </template>
    </ConfirmActionModal>

    <ConfirmActionModal
      :show="vm.showDeleteNodeConfirm"
      :title="$t('skills.editor.delete_node_dialog_title')"
      :message="$t('skills.editor.delete_node_confirm', { path: vm.deleteNodePath || '-' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.delete')"
      tone="danger"
      :loading="vm.deletingNode"
      @cancel="vm.cancelDeleteNode"
      @confirm="vm.confirmDeleteNode"
    />

    <ConfirmActionModal
      :show="vm.showRestoreConfirm"
      :title="$t('skills.editor.restore_version')"
      :message="$t('skills.editor.restore_confirm')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="primary"
      :loading="vm.restoring"
      @cancel="vm.showRestoreConfirm = false"
      @confirm="vm.confirmRestoreVersion"
    />

    <transition name="drawer-fade">
      <div v-if="vm.showRatingNotesModal" class="drawer-mask" @click="vm.showRatingNotesModal = false"></div>
    </transition>
    <transition name="drawer-slide">
      <div v-if="vm.showRatingNotesModal" class="side-drawer">
        <div class="drawer-header">
          <div class="drawer-title-area">
            <Star class="w-5 h-5 drawer-title-icon" />
            <h3>{{ $t('skills.editor.rating_notes_title') }}</h3>
          </div>
          <button class="drawer-close-btn" @click="vm.showRatingNotesModal = false">
            <X class="w-5 h-5" />
          </button>
        </div>

        <div class="drawer-content">
          <div v-if="vm.ratingNotesLoading" class="modal-loading-state">
            <Loader2 class="w-6 h-6 animate-spin text-primary" />
            <span>{{ $t('common.loading') }}...</span>
          </div>
          <div v-else-if="vm.ratingNotes.length === 0" class="modal-empty-state">
            {{ $t('skills.editor.no_ratings') }}
          </div>
          <div v-else class="rating-notes-list">
            <div v-for="item in vm.ratingNotes" :key="item.id" class="rating-note-card">
              <div class="rating-note-header">
                <div class="expert-info">
                  <UserAvatar size="sm" :avatar-svg="item.expert_avatar_svg" :display-name="item.expert_display_name" />
                  <span class="expert-name">{{ item.expert_display_name || 'Unknown' }}</span>
                </div>
                <div class="note-score">
                  <Star v-for="i in 5" :key="i" class="w-3.5 h-3.5" :class="i <= item.score ? 'star-active' : 'star-inactive'" />
                </div>
              </div>
              <p class="note-body">{{ item.note }}</p>
              <div class="note-footer">
                <span v-if="item.version_no" class="version-tag">v{{ item.version_no }}</span>
                <span class="note-time">{{ item.created_at }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
<style scoped>
.commit-note-label {
  display: block;
  margin-bottom: var(--space-2);
  font-size: 0.8125rem;
  font-weight: 600;
  color: #334155;
}

.commit-note-input {
  width: 100%;
  min-height: 100px;
  border: 1px solid #cbd5e1;
  border-radius: var(--radius-md);
  padding: 0.625rem 0.75rem;
  font-size: 0.875rem;
  line-height: 1.5;
  color: #0f172a;
  background: #fff;
  resize: vertical;
}

.commit-note-input:focus {
  outline: 2px solid rgba(59, 130, 246, 0.22);
  border-color: var(--color-primary-500);
}

.create-node-input {
  width: 100%;
  height: 42px;
  border: 1px solid #cbd5e1;
  border-radius: var(--radius-md);
  padding: 0 0.75rem;
  font-size: 0.875rem;
  color: #0f172a;
  background: #fff;
}

.create-node-input:focus {
  outline: 2px solid rgba(59, 130, 246, 0.22);
  border-color: var(--color-primary-500);
}

.modal-loading-state, .modal-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 0;
  color: #64748b;
  gap: 0.5rem;
}

.rating-notes-list {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.star-active {
  color: #f59e0b;
  fill: #f59e0b;
}

.star-inactive {
  color: #e2e8f0;
}

/* Drawer Styles */
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  z-index: 100;
}

.side-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 440px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 250, 252, 0.98) 100%);
  box-shadow: -10px 0 25px -5px rgba(0, 0, 0, 0.1), -5px 0 10px -5px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  z-index: 101;
  border-left: 1px solid rgba(255, 255, 255, 0.8);
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 1.75rem;
  border-bottom: 1px solid #f1f5f9;
}

.drawer-title-area {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.drawer-title-icon {
  color: #f59e0b;
  fill: #f59e0b;
}

.drawer-title-area h3 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  color: #1e293b;
  letter-spacing: -0.01em;
}

.drawer-close-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s ease;
}

.drawer-close-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
  transform: scale(1.05);
}

.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem 1.75rem;
}

/* Transitions */
.drawer-fade-enter-active,
.drawer-fade-leave-active {
  transition: opacity 0.3s ease;
}

.drawer-fade-enter-from,
.drawer-fade-leave-to {
  opacity: 0;
}

.drawer-slide-enter-active,
.drawer-slide-leave-active {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.drawer-slide-enter-from,
.drawer-slide-leave-to {
  transform: translateX(100%);
}

.rating-note-card {
  padding: 1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-lg);
}

.rating-note-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.expert-info {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.expert-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: #1e293b;
}

.note-score {
  display: flex;
  gap: 0.125rem;
}

.note-body {
  font-size: 0.875rem;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
  margin-bottom: 0.75rem;
}

.note-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.75rem;
  color: #94a3b8;
}

.version-tag {
  background: #f1f5f9;
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
  font-family: var(--font-mono);
}
</style>
