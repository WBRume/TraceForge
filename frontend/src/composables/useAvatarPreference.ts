import { isAxiosError } from 'axios'
import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api, { getApiServerUrl } from '@/utils/api'
import { buildAvatarSvg, type AvatarShape, type AvatarTemplateStyle, type SavedAvatar } from '@/utils/avatar'
import {
  AvatarImageError, MAX_AVATAR_ANIMATION_FRAMES, MAX_AVATAR_UPLOAD_BYTES, centeredAvatarCrop, type AvatarCrop,
} from '@/utils/avatarCrop'
import {
  AVATAR_SOURCE_LIMIT_MB, decodeAvatarImage, encodeAvatarCrop, isAnimatedAvatar, releaseAvatarImage, type AvatarImage,
} from '@/utils/avatarImage'

type AvatarMode = 'template' | 'upload'
type AvatarDraft = { image: AvatarImage; fileName: string; crop: AvatarCrop }
type AvatarSubject = Partial<SavedAvatar> & {
  id: string
  display_name?: string
  email?: string
}

type AvatarPreferenceOptions = {
  target: () => AvatarSubject | null
  endpoint: (id: string) => string
  onSaved: (id: string, avatar: SavedAvatar) => void
  canEdit: () => boolean
  shape: AvatarShape
}

export function useAvatarPreference(options?: AvatarPreferenceOptions) {
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

  const target = computed(() => options ? options.target() : auth.user)
  const shape = options?.shape ?? 'circle'
  const editable = computed(() => Boolean(target.value) && (options?.canEdit() ?? true))
  const templateOptions = computed(() => [
    { value: 'classic', label: t('settings.appearance.style_classic') },
    { value: 'soft', label: t('settings.appearance.style_soft') },
    { value: 'split', label: t('settings.appearance.style_split') },
  ])
  const templateSvg = computed(() => buildAvatarSvg({
    displayName: target.value?.display_name,
    email: target.value?.email,
    userId: target.value?.id,
    style: style.value,
    color: color.value,
    shape,
  }))
  const editing = computed(() => mode.value === 'upload' ? draft.value : null)
  const previewSvg = computed(() => mode.value === 'template' ? templateSvg.value : target.value?.avatar_svg)
  const previewUrl = computed(() => mode.value === 'upload' ? target.value?.avatar_url : null)
  const busy = computed(() => loading.value || saving.value)
  const canSave = computed(() => editable.value && !busy.value && (mode.value === 'template' || !!editing.value))
  const hasCustomAvatar = computed(() => Boolean(target.value?.avatar_svg || target.value?.avatar_url))

  function captureSession() {
    const token = auth.token
    const server = getApiServerUrl()
    return () => auth.token === token && getApiServerUrl() === server
  }

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
    if (!editable.value || busy.value) return
    clearFeedback()
    loading.value = true
    const sameSession = captureSession()
    const id = target.value?.id
    const isCurrent = () => !disposed && sameSession() && target.value?.id === id
    try {
      const image = await decodeAvatarImage(file)
      if (!isCurrent()) {
        releaseAvatarImage(image)
        return
      }
      replaceDraft({ image, fileName: file.name, crop: centeredAvatarCrop(image) })
    } catch (cause) {
      if (isCurrent()) error.value = errorMessage(cause, 'invalid_image')
    } finally {
      loading.value = false
    }
  }

  function updateCrop(crop: AvatarCrop) {
    if (!draft.value || busy.value) return
    draft.value = { ...draft.value, crop }
    clearFeedback()
  }

  async function persist(useDefault: boolean) {
    const id = target.value?.id
    const allowed = useDefault
      ? options && editable.value && !busy.value && hasCustomAvatar.value
      : canSave.value
    if (!id || !allowed) return
    clearFeedback()
    saving.value = true
    const photo = useDefault ? null : editing.value
    const svg = useDefault ? null : templateSvg.value
    const encoding = photo && isAnimatedAvatar(photo.image) ? new AbortController() : null
    activeEncoding = encoding
    const sameSession = captureSession()
    const isCurrent = () => !disposed && sameSession() && target.value?.id === id
    const endpoint = options?.endpoint(id) ?? '/auth/me/avatar'
    try {
      const image = photo ? await encodeAvatarCrop(photo.image, photo.crop, encoding?.signal) : null
      if (!isCurrent() || !editable.value || encoding?.signal.aborted) return
      const response = image
        ? await api.put<SavedAvatar>(`${endpoint}/image`, image, { headers: { 'Content-Type': image.type } })
        : await api.put<SavedAvatar>(endpoint, { avatar_svg: svg })

      if (!sameSession()) return
      const { avatar_url, avatar_svg } = response.data
      const saved = { avatar_url, avatar_svg }
      if (options) options.onSaved(id, saved)
      else if (auth.user?.id === id) auth.setUser({ ...auth.user, ...saved })

      if (!isCurrent()) return
      if (photo || useDefault) replaceDraft(null)
      if (useDefault) mode.value = 'upload'
      success.value = t(useDefault ? 'settings.workspace_avatar.reset_success' : 'settings.appearance.save_success')
    } catch (cause) {
      if (!isCurrent() || encoding?.signal.aborted) return
      if (encoding && isAxiosError(cause) && cause.response?.status === 413) {
        cause = new AvatarImageError('animation_too_large')
      }
      error.value = errorMessage(cause, 'save_failed')
    } finally {
      activeEncoding = null
      saving.value = false
    }
  }

  watch([() => auth.token, () => target.value?.id], () => {
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
    target, shape, editable, mode, style, color, templateOptions, editing, previewSvg, previewUrl,
    loading, saving, busy, canSave, hasCustomAvatar, error, success, changeMode, selectFile, updateCrop,
    save: () => persist(false),
    reset: () => persist(true),
  }
}

export type AvatarPreference = ReturnType<typeof useAvatarPreference>
