import { isAxiosError } from 'axios'
import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api, { getApiServerUrl } from '@/utils/api'
import { buildAvatarSvg, type AvatarTemplateStyle } from '@/utils/avatar'
import {
  AvatarImageError, MAX_AVATAR_ANIMATION_FRAMES, MAX_AVATAR_UPLOAD_BYTES, centeredAvatarCrop, type AvatarCrop,
} from '@/utils/avatarCrop'
import {
  AVATAR_SOURCE_LIMIT_MB, decodeAvatarImage, encodeAvatarCrop, isAnimatedAvatar, releaseAvatarImage, type AvatarImage,
} from '@/utils/avatarImage'

type AvatarMode = 'template' | 'upload'
type AvatarDraft = { image: AvatarImage; fileName: string; crop: AvatarCrop }
type SavedAvatar = { avatar_svg: string | null; avatar_url: string | null }

export function useAvatarPreference() {
  const auth = useAuthStore()
  const { t } = useI18n()
  const mode = shallowRef<AvatarMode>('upload')
  const style = shallowRef<AvatarTemplateStyle>('classic')
  const color = shallowRef('#0ea5e9')
  const draft = shallowRef<AvatarDraft | null>(null)
  const loading = shallowRef(false)
  const saving = shallowRef(false)
  const error = shallowRef('')
  const success = shallowRef('')
  let disposed = false
  let activeEncoding: AbortController | null = null

  const user = computed(() => auth.user)
  const templateOptions = computed(() => [
    { value: 'classic', label: t('settings.appearance.style_classic') },
    { value: 'soft', label: t('settings.appearance.style_soft') },
    { value: 'split', label: t('settings.appearance.style_split') },
  ])
  const templateSvg = computed(() => buildAvatarSvg({
    displayName: user.value?.display_name,
    email: user.value?.email,
    userId: user.value?.id,
    style: style.value,
    color: color.value,
  }))
  const editing = computed(() => mode.value === 'upload' ? draft.value : null)
  const previewSvg = computed(() => mode.value === 'template' ? templateSvg.value : user.value?.avatar_svg)
  const previewUrl = computed(() => mode.value === 'upload' ? user.value?.avatar_url : null)
  const busy = computed(() => loading.value || saving.value)
  const canSave = computed(() => Boolean(user.value && !busy.value && (mode.value === 'template' || editing.value)))

  function clearFeedback() {
    error.value = ''
    success.value = ''
  }

  function replaceDraft(next: AvatarDraft | null) {
    const previous = draft.value
    draft.value = next
    if (previous) releaseAvatarImage(previous.image)
  }

  function errorMessage(cause: unknown, fallback: 'invalid_image' | 'save_failed') {
    const reason = cause instanceof AvatarImageError ? cause.reason : fallback
    return t(`settings.appearance.${reason}`, {
      size: AVATAR_SOURCE_LIMIT_MB,
      frames: MAX_AVATAR_ANIMATION_FRAMES,
      uploadLimit: (MAX_AVATAR_UPLOAD_BYTES / 1024 ** 2).toFixed(2),
    })
  }

  function changeMode(next: AvatarMode) {
    if (busy.value || mode.value === next) return
    mode.value = next
    clearFeedback()
  }

  async function selectFile(file: File) {
    if (busy.value) return
    clearFeedback()
    loading.value = true
    const token = auth.token
    try {
      const image = await decodeAvatarImage(file)
      if (disposed || auth.token !== token) {
        releaseAvatarImage(image)
        return
      }
      replaceDraft({ image, fileName: file.name, crop: centeredAvatarCrop(image) })
    } catch (cause) {
      error.value = errorMessage(cause, 'invalid_image')
    } finally {
      loading.value = false
    }
  }

  function updateCrop(crop: AvatarCrop) {
    if (!draft.value || busy.value) return
    draft.value = { ...draft.value, crop }
    clearFeedback()
  }

  async function save() {
    if (!canSave.value || !auth.user) return
    clearFeedback()
    saving.value = true
    const photo = editing.value
    const encoding = photo && isAnimatedAvatar(photo.image) ? new AbortController() : null
    activeEncoding = encoding
    const userId = auth.user.id
    const token = auth.token
    const server = getApiServerUrl()
    const sameSession = () => auth.user?.id === userId && auth.token === token && getApiServerUrl() === server
    try {
      const image = photo ? await encodeAvatarCrop(photo.image, photo.crop, encoding?.signal) : null
      if (!sameSession() || encoding?.signal.aborted) return
      const response = image
        ? await api.put<SavedAvatar>('/auth/me/avatar/image', image, { headers: { 'Content-Type': image.type } })
        : await api.put<SavedAvatar>('/auth/me/avatar', { avatar_svg: templateSvg.value })

      if (!auth.user || !sameSession()) return
      auth.setUser({ ...auth.user, avatar_url: response.data.avatar_url, avatar_svg: response.data.avatar_svg })
      if (photo) replaceDraft(null)
      success.value = t('settings.appearance.save_success')
    } catch (cause) {
      if (encoding?.signal.aborted) return
      if (encoding && isAxiosError(cause) && cause.response?.status === 413) {
        cause = new AvatarImageError('animation_too_large')
      }
      error.value = errorMessage(cause, 'save_failed')
    } finally {
      activeEncoding = null
      saving.value = false
    }
  }

  watch(() => auth.token, () => {
    activeEncoding?.abort()
    replaceDraft(null)
    clearFeedback()
  })
  watch([style, color], clearFeedback)
  onScopeDispose(() => {
    disposed = true
    activeEncoding?.abort()
    replaceDraft(null)
  })

  return {
    user, mode, style, color, templateOptions, editing, previewSvg, previewUrl,
    loading, saving, busy, canSave, error, success, changeMode, selectFile, updateCrop, save,
  }
}

export type AvatarPreference = ReturnType<typeof useAvatarPreference>
