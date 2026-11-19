<script setup lang="ts">
import { proxyRefs, useId, useTemplateRef, watchPostEffect } from 'vue'
import BaseSelect from '@/components/BaseSelect.vue'
import { Loader2, Palette, Save, UploadCloud } from '@/components/icons'
import AvatarImageCrop from '@/components/settings/AvatarImageCrop.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { AvatarPreference } from '@/composables/useAvatarPreference'
import { AVATAR_FILE_ACCEPT, AVATAR_SOURCE_LIMIT_MB, drawAvatarCrop } from '@/utils/avatarImage'

const props = defineProps<{ preference: AvatarPreference }>()
const avatar = proxyRefs(props.preference)
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const preview = useTemplateRef<HTMLCanvasElement>('preview')
const previewTitle = useId()
const colorInput = useId()

watchPostEffect(() => {
  const draft = avatar.editing
  if (preview.value && draft) drawAvatarCrop(preview.value, draft.image, draft.crop)
})

function handleFileChange(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void avatar.selectFile(file)
}

function handleFileDrop(event: DragEvent) {
  const file = event.dataTransfer?.files[0]
  if (file) void avatar.selectFile(file)
}
</script>

<template>
  <section class="settings-section appearance-section">
    <div class="section-header">
      <div class="icon-circle">
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
              type="button"
              class="pill-btn"
              :class="{ active: avatar.mode === 'template' }"
              :aria-pressed="avatar.mode === 'template'"
              :disabled="avatar.busy"
              @click="avatar.changeMode('template')"
            >
              {{ $t('settings.appearance.mode_template') }}
            </button>
            <button
              type="button"
              class="pill-btn"
              :class="{ active: avatar.mode === 'upload' }"
              :aria-pressed="avatar.mode === 'upload'"
              :disabled="avatar.busy"
              @click="avatar.changeMode('upload')"
            >
              {{ $t('settings.appearance.mode_upload') }}
            </button>
          </div>
        </div>

        <div v-if="avatar.mode === 'template'" class="appearance-form-grid">
          <div class="form-group">
            <label>{{ $t('settings.appearance.template_style') }}</label>
            <BaseSelect
              v-model="avatar.style"
              :options="avatar.templateOptions"
              :disabled="avatar.saving"
              :aria-label="$t('settings.appearance.template_style')"
              size="lg"
            />
          </div>
          <div class="form-group">
            <label :for="colorInput">{{ $t('settings.appearance.theme_color') }}</label>
            <div class="color-field">
              <input :id="colorInput" v-model="avatar.color" class="color-input" type="color" :disabled="avatar.saving">
              <span>{{ avatar.color }}</span>
            </div>
          </div>
        </div>

        <div
          v-else
          class="appearance-upload"
          :aria-busy="avatar.loading"
          @dragover.prevent
          @drop.prevent="handleFileDrop"
        >
          <template v-if="avatar.editing">
            <div class="selected-image">
              <span class="file-name" :title="avatar.editing.fileName" dir="auto">{{ avatar.editing.fileName }}</span>
              <button type="button" class="replace-image" :disabled="avatar.busy" @click="fileInput?.click()">
                {{ $t(avatar.loading ? 'settings.appearance.reading_image' : 'settings.appearance.change_image') }}
              </button>
            </div>
            <AvatarImageCrop
              :image="avatar.editing.image"
              :model-value="avatar.editing.crop"
              :disabled="avatar.busy"
              @update:model-value="avatar.updateCrop"
            />
          </template>
          <button v-else type="button" class="select-image" :disabled="avatar.busy" @click="fileInput?.click()">
            <Loader2 v-if="avatar.loading" class="upload-icon spin" />
            <UploadCloud v-else class="upload-icon" />
            <strong>{{ $t(avatar.loading ? 'settings.appearance.reading_image' : 'settings.appearance.choose_image') }}</strong>
            <span class="upload-hint">{{ $t('settings.appearance.upload_hint', { size: AVATAR_SOURCE_LIMIT_MB }) }}</span>
          </button>
          <input ref="fileInput" type="file" hidden :accept="AVATAR_FILE_ACCEPT" @change="handleFileChange">
        </div>

        <div v-if="avatar.error" class="error-banner mt-sm" role="alert">{{ avatar.error }}</div>
        <div v-if="avatar.success" class="success-banner mt-sm" role="status">{{ avatar.success }}</div>

        <button type="button" class="btn-primary mt-sm" :disabled="!avatar.canSave" @click="avatar.save">
          <Loader2 v-if="avatar.saving" class="w-4 h-4 spin" />
          <Save v-else class="w-4 h-4" />
          {{ $t(avatar.saving ? 'settings.appearance.saving' : 'settings.appearance.save_avatar') }}
        </button>
      </div>

      <aside class="appearance-preview" :aria-labelledby="previewTitle">
        <div class="profile-card">
          <div class="profile-card-inner">
            <h3 :id="previewTitle" class="preview-title">{{ $t('settings.appearance.preview') }}</h3>
            <div class="preview-avatar-wrap">
              <canvas v-if="avatar.editing" ref="preview" class="crop-preview" width="256" height="256" aria-hidden="true" />
              <UserAvatar
                v-else
                :display-name="avatar.user?.display_name"
                :email="avatar.user?.email"
                :user-id="avatar.user?.id"
                :avatar-svg="avatar.previewSvg"
                :avatar-url="avatar.previewUrl"
                size="lg"
              />
            </div>
            <div class="profile-info">
              <p class="profile-name">{{ avatar.user?.display_name || avatar.user?.email || '-' }}</p>
              <p class="profile-meta">{{ avatar.user?.email }}</p>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped src="@/styles/settings/appearance.css"></style>

<style scoped>
.appearance-upload {
  min-width: 0;
}

.select-image {
  display: flex;
  width: 100%;
  min-height: 10rem;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.625rem;
  border: 1px dashed #94a3b8;
  border-radius: 0.75rem;
  padding: 1.25rem 1rem;
  background: #f8fafc;
  color: #0f172a;
  font: inherit;
  cursor: pointer;
}

.select-image:hover:not(:disabled) {
  border-color: #0284c7;
  background: #f0f9ff;
}

.upload-icon {
  width: 1.75rem;
  height: 1.75rem;
  color: #0284c7;
}

.upload-hint {
  max-width: 28rem;
  color: #475569;
  font-size: 0.8125rem;
}

.selected-image {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.8125rem;
}

.file-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #475569;
}

.replace-image {
  flex-shrink: 0;
  border: 1px solid #bae6fd;
  border-radius: 0.5rem;
  padding: 0.375rem 0.625rem;
  background: white;
  color: #0369a1;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.replace-image:hover:not(:disabled) {
  background: #e0f2fe;
}

.select-image:disabled,
.replace-image:disabled,
.pill-btn:disabled {
  cursor: default;
}

.preview-title {
  margin: 0;
  color: #475569;
  font-size: 0.875rem;
  font-weight: 600;
}

.preview-avatar-wrap {
  display: inline-flex;
  max-width: 100%;
}

.preview-avatar-wrap :deep(.user-avatar),
.crop-preview {
  width: 6.5rem;
  height: 6.5rem;
  border: 1px solid #93c5fd;
  border-radius: 50%;
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  font-size: 2.5rem;
}

.profile-info {
  max-width: 100%;
  overflow-wrap: anywhere;
}

@media (max-width: 640px) {
  .profile-card-inner {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 0.375rem 1rem;
    padding: 1rem;
    text-align: left;
  }

  .preview-title {
    grid-column: 2;
    align-self: end;
  }

  .preview-avatar-wrap {
    grid-column: 1;
    grid-row: 1 / 3;
  }

  .preview-avatar-wrap :deep(.user-avatar),
  .crop-preview {
    width: 4rem;
    height: 4rem;
    font-size: 1.5rem;
  }

  .profile-info {
    grid-column: 2;
    align-self: start;
  }
}
</style>
