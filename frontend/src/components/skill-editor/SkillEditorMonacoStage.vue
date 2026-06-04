<script setup lang="ts">
import { computed, proxyRefs, shallowRef, watch, onBeforeUnmount } from 'vue'
import { Info, Loader2 } from 'lucide-vue-next'
import { VueMonacoDiffEditor, VueMonacoEditor } from '@guolao/vue-monaco-editor'
import SkillFileTabs from '@/components/skill-editor/SkillFileTabs.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'
import type * as Monaco from 'monaco-editor'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const rawVm = props.vm
const vm = proxyRefs(rawVm)

const activeIsBinary = computed(() => Boolean(vm.binaryFileMap[vm.activeFilePath]))

const diffEditorRef = shallowRef<Monaco.editor.IStandaloneDiffEditor | null>(null)
const handleDiffMount = (editor: Monaco.editor.IStandaloneDiffEditor) => {
  diffEditorRef.value = editor
}

watch(() => vm.isDiffMode, (isDiff) => {
  if (!isDiff && diffEditorRef.value) {
    diffEditorRef.value.setModel(null)
  }
})

onBeforeUnmount(() => {
  if (diffEditorRef.value) {
    diffEditorRef.value.setModel(null)
  }
})
</script>

<template>
  <div
    :ref="rawVm.editorStageRef"
    class="editor-stage"
    @pointerdown="vm.handleEditorStagePointerDown"
  >
    <SkillFileTabs :vm="rawVm" />

    <div v-if="!vm.activeFilePath" class="editor-empty">
      <Info class="w-4 h-4" />
      <span>{{ $t('skills.editor.file_tree_empty') }}</span>
    </div>

    <div v-else-if="vm.loadingFile" class="editor-empty">
      <Loader2 class="w-4 h-4 animate-spin" />
      <span>{{ $t('skills.editor.loading') }}</span>
    </div>

    <div v-else-if="activeIsBinary && !vm.isDiffMode" class="editor-empty">
      <Info class="w-4 h-4" />
      <span>{{ $t('skills.editor.binary_file_hint') }}</span>
    </div>

    <template v-else>
      <div class="monaco-shell" :class="{ 'with-avatar-rail': vm.showLineReviewAvatars }">
        <div v-if="vm.showLineReviewAvatars" class="avatar-rail custom-scrollbar">
          <div v-if="vm.lineAvatarSlots.length > 0" class="line-avatar-layer">
            <div
              v-for="slot in vm.lineAvatarSlots"
              :key="`line-avatar-${slot.line}`"
              class="line-avatar-row"
              :style="{ top: `${slot.top}px`, left: `${slot.left}px` }"
            >
              <button
                type="button"
                class="line-avatar-stack-btn"
                data-review-avatar="true"
                @click.stop="vm.openReviewerPopover(slot, $event)"
              >
                <span class="line-avatar-stack-group">
                  <span
                    v-for="(reviewer, idx) in slot.stackReviewers"
                    :key="`${slot.line}-${reviewer.userId}`"
                    class="line-avatar-stack-item"
                    :class="{ primary: idx === 0 }"
                    :style="{ zIndex: `${slot.stackReviewers.length - idx}` }"
                  >
                    <UserAvatar
                      :display-name="reviewer.displayName"
                      :user-id="reviewer.userId"
                      :avatar-svg="reviewer.avatarSvg"
                      size="xs"
                      :accent-color="vm.reviewerColor(reviewer.userId)"
                    />
                  </span>
                </span>
              </button>
              <span class="line-avatar-more">{{ slot.totalCommentCount }}</span>
            </div>
          </div>
        </div>

        <div class="monaco-main">
          <VueMonacoEditor
            v-if="!vm.isDiffMode"
            v-model:value="vm.activeFileContent"
            :language="vm.activeLanguage"
            theme="vs"
            :options="vm.editorOptions"
            width="100%"
            height="calc(100vh - 430px)"
            @mount="vm.handleEditorMount"
          />
          <VueMonacoDiffEditor
            v-else
            :original="vm.diffPayload.original"
            :modified="vm.diffPayload.modified"
            :language="vm.activeLanguage"
            theme="vs"
            :options="vm.diffEditorOptions"
            width="100%"
            height="calc(100vh - 430px)"
            @mount="handleDiffMount"
          />
        </div>
      </div>
    </template>

    <transition name="pop">
      <div
        v-if="vm.avatarPopover.visible"
        :ref="rawVm.avatarPopoverRef"
        class="review-popover glass-panel"
        :style="{ top: `${vm.avatarPopover.top}px`, left: `${vm.avatarPopover.left}px` }"
        @pointerdown.stop
        @click.stop
      >
        <div class="review-popover-head">
          <div class="review-popover-author">
            <UserAvatar
              :display-name="vm.popoverReviewerName"
              :user-id="vm.avatarPopover.userId"
              :avatar-svg="vm.popoverReviewerAvatarSvg"
              size="sm"
              :accent-color="vm.popoverReviewerColor"
            />
            <div class="author-info">
              <strong>{{ vm.popoverReviewerName }}</strong>
              <span>{{ $t('skills.editor.comment_line_range', { start: vm.avatarPopover.line, end: vm.avatarPopover.line }) }}</span>
            </div>
          </div>
          <button class="close-btn-sm" @click="vm.closeAvatarPopover">&times;</button>
        </div>

        <div v-if="vm.popoverLineReviewers.length > 1" class="review-popover-reviewers scrollbar-hide">
          <button
            v-for="reviewer in vm.popoverLineReviewers"
            :key="`popover-reviewer-${vm.avatarPopover.line}-${reviewer.userId}`"
            type="button"
            class="reviewer-switch-btn"
            :class="{ active: reviewer.userId === vm.avatarPopover.userId }"
            @click="vm.switchPopoverReviewer(reviewer)"
          >
            <UserAvatar
              :display-name="reviewer.displayName"
              :user-id="reviewer.userId"
              :avatar-svg="reviewer.avatarSvg"
              size="xs"
              :accent-color="vm.reviewerColor(reviewer.userId)"
            />
          </button>
        </div>

        <div class="review-popover-list custom-scrollbar">
          <div
            v-for="comment in vm.activePopoverComments"
            :key="`popover-comment-${comment.id}`"
            class="review-popover-item"
            :class="{ active: vm.activeCommentId === comment.id }"
            @click="vm.pickPopoverComment(comment)"
          >
            <p>{{ comment.body }}</p>
            <span class="comment-date">{{ vm.formatDateTime(comment.created_at) }}</span>
          </div>
          <p v-if="vm.activePopoverComments.length === 0" class="hint">{{ $t('skills.editor.comment_empty') }}</p>
        </div>
      </div>
    </transition>

    <transition name="pop">
      <div
        v-if="!vm.isDiffMode && vm.canLineReview && vm.selectedRange && vm.inlineComposerPosition.visible"
        class="inline-composer-float glass-panel"
        :style="{
          top: `${vm.inlineComposerPosition.top}px`,
          left: `${vm.inlineComposerPosition.left}px`,
          maxWidth: `${vm.inlineComposerPosition.maxWidth}px`
        }"
        @mousedown.stop
        @click.stop
        @pointerdown.stop
      >
        <div class="inline-composer-head">
          <strong>{{ $t('skills.editor.comment_title') }}</strong>
          <span>L{{ vm.selectedRange.line_start }} - L{{ vm.selectedRange.line_end }}</span>
        </div>
        <textarea
          v-model="vm.commentBody"
          class="inline-composer-input"
          :placeholder="$t('skills.editor.comment_placeholder')"
          @focus="vm.isInlineComposerFocused = true"
          @blur="vm.isInlineComposerFocused = false"
        />
        <div class="inline-composer-actions">
          <button class="btn-ghost-xs" @click="vm.clearSelectedRange">{{ $t('common.cancel') }}</button>
          <button class="btn-primary-xs" :disabled="!vm.canSubmitComment || vm.commentSaving" @click="vm.submitComment">
            <Loader2 v-if="vm.commentSaving" class="w-3 h-3 animate-spin" />
            {{ $t('skills.editor.submit_comment') }}
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
