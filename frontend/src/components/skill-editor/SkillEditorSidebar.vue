<script setup lang="ts">
import { proxyRefs } from 'vue'
import { ArrowRight, GitCompare, History, Info, Loader2, MessageSquare, RotateCcw, Star } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <aside class="sidebar">
    <section class="side-card glass-panel">
      <h3 class="side-card-title">{{ $t('skills.editor.review_title') }}</h3>
      <div class="review-overview">
        <div class="stat-badge sky">
          <Star class="w-4 h-4" />
          <span>{{ vm.reviewOverview.average_score ?? '-' }}</span>
        </div>
        <div class="stat-badge clickable" :title="$t('skills.editor.view_ratings')" @click="vm.loadRatingNotes">
          <MessageSquare class="w-4 h-4" />
          <span>{{ vm.reviewOverview.review_count }}</span>
        </div>
        <div class="stat-badge">
          <History class="w-4 h-4" />
          <span>v{{ vm.reviewOverview.current_version_no || '-' }}</span>
        </div>
      </div>

      <div v-if="vm.canReview" class="side-form mt">
        <div class="score-selector">
          <button
            v-for="score in [1, 2, 3, 4, 5]"
            :key="score"
            class="score-dot"
            :class="{ active: vm.ratingForm.score >= score }"
            @click="vm.ratingForm.score = score"
          >
            <Star class="w-5 h-5 fill-current" />
          </button>
        </div>
        <textarea
          v-model="vm.ratingForm.note"
          class="side-textarea sm"
          :class="{ 'has-error': vm.showRatingNoteError }"
          :placeholder="$t('skills.editor.rating_note_placeholder')"
        />
        <button class="btn-primary-sm" :disabled="vm.ratingSaving || vm.ratingForm.score <= 0" @click="vm.submitRating">
          <Loader2 v-if="vm.ratingSaving" class="w-4 h-4 animate-spin" />
          <span>{{ $t('skills.editor.submit_rating') }}</span>
        </button>
      </div>
      <p v-else class="hint-text text-center">{{ $t('skills.editor.review_readonly_hint') }}</p>
    </section>

    <section class="side-card glass-panel">
      <h3 class="side-card-title">{{ $t('skills.editor.version_title') }}</h3>
      <div v-if="vm.versionsLoading" class="loading-state">
        <Loader2 class="w-4 h-4 animate-spin" />
        <span>{{ $t('skills.editor.version_loading') }}</span>
      </div>
      <template v-else>
        <div class="side-form">
          <div class="side-form-group">
            <label>{{ $t('skills.editor.view_target') }}</label>
            <BaseSelect v-model="vm.viewVersionId" :options="vm.versionOptions" />
            <div v-if="vm.isViewingHistoricalVersion" class="info-badge mt-xs">
              <Info class="w-3.5 h-3.5" />
              <span>{{ $t('skills.editor.historical_readonly_hint', { version: vm.resolveVersionNo(vm.viewVersionId) || '-' }) }}</span>
            </div>
          </div>

          <button class="btn-outline-sm" :disabled="!vm.canRestoreSelectedVersion" @click="vm.showRestoreConfirm = true">
            <RotateCcw class="w-4 h-4" />
            <span>{{ $t('skills.editor.restore_version') }}</span>
          </button>

          <div class="h-divider my-sm"></div>

          <div class="side-form-group">
            <label>{{ $t('skills.editor.compare_versions') }}</label>
            <div class="compare-grid">
              <BaseSelect v-model="vm.compareFromVersionId" :options="vm.versionSimpleOptions" size="sm" />
              <ArrowRight class="compare-arrow w-4 h-4" />
              <BaseSelect v-model="vm.compareToVersionId" :options="vm.versionSimpleOptions" size="sm" />
            </div>
          </div>

          <button
            class="btn-outline-sm"
            :disabled="vm.diffLoading || !vm.compareFromVersionId || !vm.compareToVersionId"
            @click="vm.loadDirectoryDiff"
          >
            <Loader2 v-if="vm.diffLoading" class="w-4 h-4 animate-spin" />
            <GitCompare v-else class="w-4 h-4" />
            <span>{{ $t('skills.editor.load_diff') }}</span>
          </button>

          <button v-if="vm.isDiffMode" class="btn-primary-sm mt-xs" @click="vm.switchToEditContentView">
            <RotateCcw class="w-4 h-4" />
            <span>{{ $t('skills.editor.back_to_edit') }}</span>
          </button>
        </div>
      </template>
    </section>
  </aside>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
