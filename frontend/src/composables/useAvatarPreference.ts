import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api, { getApiServerUrl } from '@/utils/api'
import { buildAvatarSvg, type AvatarTemplateStyle } from '@/utils/avatar'
import {
  AVATAR_SOURCE_LIMIT_MB, AvatarImageError, centeredAvatarCrop, decodeAvatarImage, encodeAvatarCrop, type AvatarCrop,
} from '@/utils/avatarImage'

type AvatarMode = 'template' | 'upload'
type AvatarDraft = { image: ImageBitmap; fileName: string; crop: AvatarCrop }
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
    previous?.image.close()
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
        image.close()
        return
      }
      replaceDraft({ image, fileName: file.name, crop: centeredAvatarCrop(image) })
    } catch (cause) {
      const reason = cause instanceof AvatarImageError ? cause.reason : 'invalid_image'
      error.value = t(`settings.appearance.${reason}`, { size: AVATAR_SOURCE_LIMIT_MB })
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
    const userId = auth.user.id
    const token = auth.token
    const server = getApiServerUrl()
    const sameSession = () => auth.user?.id === userId && auth.token === token && getApiServerUrl() === server
    try {
      const image = photo ? await encodeAvatarCrop(photo.image, photo.crop) : null
      if (!sameSession()) return
      const response = image
        ? await api.put<SavedAvatar>('/auth/me/avatar/image', image, { headers: { 'Content-Type': image.type } })
        : await api.put<SavedAvatar>('/auth/me/avatar', { avatar_svg: templateSvg.value })

      if (!auth.user || !sameSession()) return
      auth.setUser({ ...auth.user, avatar_url: response.data.avatar_url, avatar_svg: response.data.avatar_svg })
      if (photo) replaceDraft(null)
      success.value = t('settings.appearance.save_success')
    } catch {
      error.value = t('settings.appearance.save_failed')
    } finally {
      saving.value = false
    }
  }

  watch(() => auth.token, () => {
    replaceDraft(null)
    clearFeedback()
  })
  watch([style, color], clearFeedback)
  onScopeDispose(() => {
    disposed = true
    replaceDraft(null)
  })

  return {
    user, mode, style, color, templateOptions, editing, previewSvg, previewUrl,
    loading, saving, busy, canSave, error, success, changeMode, selectFile, updateCrop, save,
  }
}

export type AvatarPreference = ReturnType<typeof useAvatarPreference>
