<script setup lang="ts">
import { ref, proxyRefs } from 'vue'
import { Loader2, Palette, Save, UploadCloud, CheckCircle2, Info } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)

const fileInput = ref<HTMLInputElement | null>(null)
const triggerFileUpload = () => {
  fileInput.value?.click()
}
</script>

<template>
  <section class="settings-section appearance-section">
    <div class="section-header">
      <div class="icon-circle appearance-icon">
        <Palette class="w-6 h-6" />
      </div>
      <div class="section-title-group">
        <h2 class="title-gradient-sm">{{ $t('settings.appearance.title') }}</h2>
        <p>{{ $t('settings.appearance.subtitle') }}</p>
      </div>
    </div>

    <div class="appearance-layout">
      <div class="appearance-card">
        <div class="pill-switcher-wrap">
          <div class="pill-switcher">
            <button
              class="pill-btn"
              :class="{ active: vm.avatarMode === 'template' }"
              @click="vm.avatarMode = 'template'"
            >
              {{ $t('settings.appearance.mode_template') }}
            </button>
            <button
              class="pill-btn"
              :class="{ active: vm.avatarMode === 'upload' }"
              @click="vm.avatarMode = 'upload'"
            >
              {{ $t('settings.appearance.mode_upload') }}
            </button>
          </div>
        </div>

        <div v-if="vm.avatarMode === 'template'" class="appearance-form-grid">
          <div class="form-group">
            <label>{{ $t('settings.appearance.template_style') }}</label>
            <BaseSelect
              v-model="vm.avatarTemplateStyle"
              :options="vm.avatarTemplateOptions"
              size="lg"
            />
          </div>
          <div class="form-group">
            <label>{{ $t('settings.appearance.theme_color') }}</label>
            <div class="color-field">
              <input v-model="vm.avatarTemplateColor" class="color-input" type="color">
              <span>{{ vm.avatarTemplateColor }}</span>
            </div>
          </div>
        </div>

        <div v-else class="appearance-upload">
          <label>{{ $t('settings.appearance.upload_label') }}</label>
          
          <div class="selection-prompt" @click="triggerFileUpload">
            <div class="prompt-icon pulse-animation">
              <UploadCloud class="w-8 h-8" />
            </div>
            <h3 class="mt-2 font-bold text-base text-primary-900">{{ $t('settings.appearance.mode_upload') }}</h3>
            <p class="text-xs text-muted mt-1 text-center max-w-sm">{{ $t('settings.appearance.upload_hint') }}</p>
            
            <div v-if="vm.uploadedFileName" class="interactive-tip mt-4">
              <CheckCircle2 class="w-4 h-4 text-emerald-500" />
              <span class="truncate max-w-[180px]">{{ vm.uploadedFileName }}</span>
            </div>
            <div v-else class="interactive-tip mt-4">
              <Info class="w-3.5 h-3.5" />
              <span>选择 SVG 文件</span>
            </div>
          </div>

          <input
            ref="fileInput"
            class="hidden-input"
            type="file"
            accept=".svg,image/svg+xml"
            @change="vm.handleAvatarFileChange"
          >
        </div>

        <div v-if="vm.appearanceError" class="error-banner mt-sm">{{ vm.appearanceError }}</div>
        <div v-if="vm.appearanceSuccess" class="success-banner mt-sm">{{ vm.appearanceSuccess }}</div>

        <button class="btn-primary mt-sm" :disabled="vm.avatarSaving" @click="vm.saveAvatarPreference">
          <Loader2 v-if="vm.avatarSaving" class="w-4 h-4 spin" />
          <Save v-else class="w-4 h-4" />
          {{ vm.avatarSaving ? $t('settings.appearance.saving') : $t('settings.appearance.save_avatar') }}
        </button>
      </div>

      <aside class="appearance-preview">
        <div class="profile-card">
          <div class="profile-card-inner">
            <div class="profile-avatar-glow">
              <div class="preview-avatar-wrap">
                <UserAvatar
                  :display-name="vm.authStore.user?.display_name"
                  :email="vm.authStore.user?.email"
                  :user-id="vm.authStore.user?.id"
                  :avatar-svg="vm.previewAvatarSvg"
                  :avatar-url="vm.previewAvatarUrl"
                  size="lg"
                />
              </div>
            </div>
            <div class="profile-info">
              <h3 class="profile-name">{{ vm.authStore.user?.display_name || vm.authStore.user?.email || '-' }}</h3>
              <p class="profile-meta">{{ vm.authStore.user?.email }}</p>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>

<style scoped>
.appearance-upload {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.selection-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 1.25rem 1rem;
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.6);
  cursor: pointer;
  transition: all 0.3s ease;
  margin-top: 0.25rem;
}

.selection-prompt:hover {
  border-color: #0ea5e9;
  background: #f0f9ff;
  transform: translateY(-2px);
  box-shadow: 0 10px 25px -5px rgba(14, 165, 233, 0.1);
}

.selection-prompt:hover .prompt-icon {
  color: #0ea5e9;
  transform: scale(1.05);
}

.prompt-icon {
  color: #94a3b8;
  transition: all 0.3s ease;
}

.interactive-tip {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.65rem;
  background: rgba(15, 23, 42, 0.04);
  border-radius: 20px;
  color: #64748b;
  font-size: 0.7rem;
}

.hidden-input {
  display: none;
}

.text-primary-900 {
  color: #0f172a;
}

.text-muted {
  color: #64748b;
}

.font-bold {
  font-weight: 700;
}

.text-lg {
  font-size: 1.125rem;
}

.text-sm {
  font-size: 0.875rem;
}

.mt-1 {
  margin-top: 0.25rem;
}

.mt-2 {
  margin-top: 0.5rem;
}

.mt-4 {
  margin-top: 1rem;
}

.text-center {
  text-align: center;
}

.max-w-sm {
  max-width: 24rem;
}

.text-base {
  font-size: 1rem;
}

.text-xs {
  font-size: 0.75rem;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(0.98); }
}

.pulse-animation {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
</style>


