<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Workflow } from '@/components/icons'
import { formatApiError } from '@/utils/error'
import { useAuthStore, type AssetDisplayMode } from '@/stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const draft = shallowRef<AssetDisplayMode>(auth.assetDisplayMode)
const saved = shallowRef(false)
const error = shallowRef('')
const modes = ['table', 'canvas'] as const

watch(() => auth.assetDisplayMode, mode => { draft.value = mode })

async function save() {
  saved.value = false
  error.value = ''
  try {
    await auth.setAssetDisplayMode(draft.value)
    saved.value = true
  } catch (cause) {
    error.value = formatApiError(cause, t('workspace_canvas.settings.save_failed'), t)
  }
}
</script>

<template>
  <div class="choice-settings">
    <form class="settings-card glass-panel animate-pop-in" @submit.prevent="save">
      <header class="section-title-row">
        <div class="flex items-start gap-4">
          <div class="icon-wrapper"><Workflow class="w-6 h-6" /></div>
          <div>
            <h2 class="title-gradient-small">{{ t('workspace_canvas.settings.title') }}</h2>
            <p class="subtitle">{{ t('workspace_canvas.settings.description') }}</p>
          </div>
        </div>
      </header>
      <div class="option-list mt-6" role="radiogroup" :aria-label="t('workspace_canvas.display_mode')">
        <label v-for="mode in modes" :key="mode" class="option-row" :class="{ selected: mode === draft }">
          <input v-model="draft" type="radio" name="asset-display" :value="mode"
            :disabled="auth.savingAssetDisplay || !auth.user" @change="saved = false; error = ''" />
          <span class="option-body">
            <strong class="option-name">{{ t(`workspace_canvas.mode.${mode}`) }}</strong>
            <span class="option-desc">{{ t(`workspace_canvas.settings.${mode}_hint`) }}</span>
          </span>
        </label>
      </div>
      <p v-if="error" class="error-text mt-4" role="alert">{{ error }}</p>
      <p v-else-if="saved" class="success-text mt-4" role="status">{{ t('workspace_canvas.settings.saved') }}</p>
      <div class="actions mt-6">
        <button class="btn-primary" type="submit" :disabled="!auth.user || auth.savingAssetDisplay || draft === auth.assetDisplayMode">
          {{ t(auth.savingAssetDisplay ? 'workspace_canvas.saving' : 'common.save') }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped src="@/styles/settings/choice-section.css"></style>
