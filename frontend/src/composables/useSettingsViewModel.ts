import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Bell, Languages, MonitorCog, Palette, Shield, Users } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'
import { buildAvatarSvg, isSvgText } from '@/utils/avatar'
import type { AvatarTemplateStyle } from '@/utils/avatar'
import { createEmptyPermissions, defaultPermissionsByRole, type PermissionFlags, type PermissionKey } from '@/utils/settingsPermissions'

export function useSettingsViewModel() {

  type WorkspaceMember = {
    id: string
    workspace_id: string
    user_id: string
    email: string
    display_name: string
    role: 'OWNER' | 'DEVELOPER' | 'VIEWER'
    joined_at: string
    permissions: PermissionFlags
    is_owner: boolean
    is_expert: boolean
  }
  
  type MemberDraft = {
    role: 'DEVELOPER' | 'VIEWER'
    permissions: PermissionFlags
    is_expert: boolean
  }
  
  type MyPermissionPayload = {
    workspace_id: string
    role: string
    permissions: PermissionFlags
    can_delete_workspace: boolean
  }
  
  type WorkspaceMemberListPayload = {
    owner: WorkspaceMember | null
    items: WorkspaceMember[]
    total: number
    page: number
    page_size: number
  }
  
  const MEMBER_PAGE_SIZE = 5
  
  const route = useRoute()
  const { locale, t } = useI18n()
  const authStore = useAuthStore()
  
  const currentLang = ref(locale.value)
  const activeSection = ref('general')
  
  const workspaceId = computed(() => String(route.params.wsId || ''))
  
  const myPermissionPayload = ref<MyPermissionPayload | null>(null)
  const ownerMember = ref<WorkspaceMember | null>(null)
  const members = ref<WorkspaceMember[]>([])
  const memberDrafts = ref<Record<string, MemberDraft>>({})
  const memberPermissionExpanded = ref<Record<string, boolean>>({})
  const memberTotal = ref(0)
  const memberPage = ref(1)
  const memberKeywordInput = ref('')
  const memberKeywordQuery = ref('')
  
  const loadingMembers = ref(false)
  const membersError = ref('')
  const addingMember = ref(false)
  const savingMemberId = ref('')
  const removingMemberId = ref('')
  const showRemoveConfirm = ref(false)
  const memberToRemove = ref<WorkspaceMember | null>(null)
  const avatarMode = ref<'template' | 'upload'>('template')
  const avatarTemplateStyle = ref<AvatarTemplateStyle>('classic')
  const avatarTemplateColor = ref('#0ea5e9')
  const uploadedSvg = ref('')
  const uploadedSvgPreviewUrl = ref('')
  const uploadedFileName = ref('')
  const avatarSaving = ref(false)
  const appearanceError = ref('')
  const appearanceSuccess = ref('')
  
  const addForm = reactive({
    user_email: '',
    role: 'DEVELOPER' as 'DEVELOPER' | 'VIEWER',
    is_expert: false,
    permissions: defaultPermissionsByRole('DEVELOPER'),
  })
  
  const permissionOptions = computed(() => [
    { key: 'create_task' as PermissionKey, label: t('settings.members.permissions.create_task') },
    { key: 'start_task' as PermissionKey, label: t('settings.members.permissions.start_task') },
    { key: 'manage_task_status' as PermissionKey, label: t('settings.members.permissions.manage_task_status') },
    { key: 'delete_task' as PermissionKey, label: t('settings.members.permissions.delete_task') },
    { key: 'upload_task_spec' as PermissionKey, label: t('settings.members.permissions.upload_task_spec') },
    { key: 'manage_skills' as PermissionKey, label: t('settings.members.permissions.manage_skills') },
    { key: 'manage_members' as PermissionKey, label: t('settings.members.permissions.manage_members') },
    { key: 'view_dashboard' as PermissionKey, label: t('settings.members.permissions.view_dashboard') },
    { key: 'view_assets' as PermissionKey, label: t('settings.members.permissions.view_assets') },
    { key: 'manage_requirements' as PermissionKey, label: t('settings.members.permissions.manage_requirements') },
    { key: 'export_task' as PermissionKey, label: t('settings.members.permissions.export_task') },
    { key: 'view_api_mock' as PermissionKey, label: t('settings.members.permissions.view_api_mock') },
    { key: 'manage_api_mock' as PermissionKey, label: t('settings.members.permissions.manage_api_mock') },
    { key: 'publish_api_mock' as PermissionKey, label: t('settings.members.permissions.publish_api_mock') },
  ])
  
  const settingsSections = computed(() => [
    {
      id: 'general',
      icon: Languages,
      label: 'settings.language',
      description: 'settings.language_desc',
    },
    {
      id: 'members',
      icon: Users,
      label: 'settings.members.title',
      description: 'settings.members.subtitle',
    },
    {
      id: 'appearance',
      icon: Palette,
      label: 'settings.theme',
      description: 'settings.theme_desc',
    },
    {
      id: 'local_dev',
      icon: MonitorCog,
      label: 'settings.local_dev.repo_mapping_title',
      description: 'settings.local_dev.repo_mapping_desc',
    },
    {
      id: 'notifications',
      icon: Bell,
      label: 'settings.notifications',
      description: 'settings.notifications_desc',
      disabled: true,
    },
    {
      id: 'security',
      icon: Shield,
      label: 'settings.security',
      description: 'settings.security_desc',
      disabled: true,
    },
  ])
  
  const canManageMembers = computed(() => Boolean(myPermissionPayload.value?.permissions?.manage_members))
  const totalMemberCount = computed(() => memberTotal.value + (ownerMember.value ? 1 : 0))
  const totalMemberPages = computed(() => Math.max(1, Math.ceil(memberTotal.value / MEMBER_PAGE_SIZE)))
  const permissionOptionCount = computed(() => permissionOptions.value.length)
  const avatarTemplateOptions = computed(() => [
    { value: 'classic' as AvatarTemplateStyle, label: t('settings.appearance.style_classic') },
    { value: 'soft' as AvatarTemplateStyle, label: t('settings.appearance.style_soft') },
    { value: 'split' as AvatarTemplateStyle, label: t('settings.appearance.style_split') },
  ])
  const memberRoleOptions = computed(() => [
    { value: 'DEVELOPER', label: t('settings.members.role_developer') },
    { value: 'VIEWER', label: t('settings.members.role_viewer') },
  ])
  const previewAvatarSvg = computed(() => {
    const templateSvg = buildAvatarSvg({
      displayName: authStore.user?.display_name || '',
      email: authStore.user?.email || '',
      userId: authStore.user?.id || '',
      color: avatarTemplateColor.value,
      style: avatarTemplateStyle.value,
    })
    if (avatarMode.value === 'upload') {
      if (uploadedSvgPreviewUrl.value) {
        return ''
      }
      return authStore.user?.avatar_svg || templateSvg
    }
    return templateSvg
  })
  const previewAvatarUrl = computed(() => (
    avatarMode.value === 'upload' ? uploadedSvgPreviewUrl.value : ''
  ))
  
  const changeLanguage = (lang: string) => {
    currentLang.value = lang
    locale.value = lang
    localStorage.setItem('sdd_lang', lang)
  }
  
  const clearAppearanceMessage = () => {
    appearanceError.value = ''
    appearanceSuccess.value = ''
  }
  
  const isAvatarSvgValidationError = (error: unknown) => {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    return typeof detail === 'string' && detail.toLowerCase().includes('svg')
  }
  
  const roleTag = (role: string) => {
    if (role === 'OWNER') return t('settings.members.role_owner')
    if (role === 'DEVELOPER') return t('settings.members.role_developer')
    return t('settings.members.role_viewer')
  }
  
  const resetAddFormByRole = () => {
    addForm.permissions = defaultPermissionsByRole(addForm.role)
  }
  
  watch(() => addForm.role, resetAddFormByRole)
  
  const seedMemberDrafts = () => {
    const nextDrafts: Record<string, MemberDraft> = {}
    for (const member of members.value) {
      if (member.role === 'OWNER') continue
      nextDrafts[member.id] = {
        role: member.role === 'VIEWER' ? 'VIEWER' : 'DEVELOPER',
        permissions: createEmptyPermissions(member.permissions),
        is_expert: Boolean(member.is_expert),
      }
    }
    memberDrafts.value = nextDrafts
  }
  
  const seedPermissionExpandState = () => {
    const nextState: Record<string, boolean> = {}
    if (ownerMember.value) {
      nextState[ownerMember.value.id] = false
    }
    for (const member of members.value) {
      nextState[member.id] = false
    }
    memberPermissionExpanded.value = nextState
  }
  
  const isPermissionExpanded = (memberId: string) => Boolean(memberPermissionExpanded.value[memberId])
  
  const togglePermissionExpanded = (memberId: string) => {
    memberPermissionExpanded.value[memberId] = !memberPermissionExpanded.value[memberId]
  }
  
  const enabledPermissionCount = (member: WorkspaceMember) => (
    permissionOptions.value.reduce((total, option) => total + (member.permissions[option.key] ? 1 : 0), 0)
  )
  
  const getDraft = (member: WorkspaceMember): MemberDraft => {
    const draft = memberDrafts.value[member.id]
    if (draft) return draft
    return {
      role: member.role === 'VIEWER' ? 'VIEWER' : 'DEVELOPER',
      permissions: createEmptyPermissions(member.permissions),
      is_expert: Boolean(member.is_expert),
    }
  }
  
  const applyDraftRoleDefaults = (memberId: string) => {
    const draft = memberDrafts.value[memberId]
    if (!draft) return
    draft.permissions = defaultPermissionsByRole(draft.role)
  }
  
  const loadAppearanceStateFromUser = () => {
    if (!authStore.user) return
    const savedSvg = authStore.user.avatar_svg?.trim() || ''
    if (!savedSvg) return
    uploadedSvg.value = savedSvg
    avatarMode.value = 'upload'
  }
  
  const handleAvatarFileChange = async (event: Event) => {
    const input = event.target as HTMLInputElement | null
    const file = input?.files?.[0]
    if (!file) return
  
    clearAppearanceMessage()
    const lowerName = file.name.toLowerCase()
    if (!(file.type === 'image/svg+xml' || lowerName.endsWith('.svg'))) {
      appearanceError.value = t('settings.appearance.invalid_file')
      return
    }
  
    try {
      const text = (await file.text()).trim()
      if (!isSvgText(text)) {
        appearanceError.value = t('settings.appearance.invalid_svg')
        return
      }
      uploadedSvg.value = text
      uploadedSvgPreviewUrl.value = `data:image/svg+xml;utf8,${encodeURIComponent(text)}`
      uploadedFileName.value = file.name
      avatarMode.value = 'upload'
    } catch {
      appearanceError.value = t('settings.appearance.invalid_svg')
    }
  }
  
  const saveAvatarPreference = async () => {
    clearAppearanceMessage()
    if (!authStore.user) {
      await authStore.fetchCurrentUser()
    }
  
    const avatarSvg = avatarMode.value === 'upload'
      ? uploadedSvg.value.trim()
      : buildAvatarSvg({
        displayName: authStore.user?.display_name || '',
        email: authStore.user?.email || '',
        userId: authStore.user?.id || '',
        color: avatarTemplateColor.value,
        style: avatarTemplateStyle.value,
      }).trim()
  
    if (!avatarSvg || !isSvgText(avatarSvg)) {
      appearanceError.value = t('settings.appearance.invalid_svg')
      return
    }
  
    avatarSaving.value = true
    try {
      const res = await api.put('/auth/me/avatar', { avatar_svg: avatarSvg })
      authStore.setUser(res.data)
      uploadedSvg.value = res.data.avatar_svg || avatarSvg
      uploadedSvgPreviewUrl.value = ''
      appearanceSuccess.value = t('settings.appearance.save_success')
    } catch (error) {
      if (isAvatarSvgValidationError(error)) {
        appearanceError.value = t('settings.appearance.invalid_svg')
      } else {
        appearanceError.value = formatApiError(error, t('settings.appearance.save_failed'), t)
      }
    } finally {
      avatarSaving.value = false
    }
  }
  
  const loadMembers = async (options?: { page?: number; keyword?: string }) => {
    if (!workspaceId.value) return
    const requestPage = options?.page ?? memberPage.value
    const requestKeyword = (options?.keyword ?? memberKeywordQuery.value).trim()
    loadingMembers.value = true
    membersError.value = ''
    try {
      const [permissionRes, membersRes] = await Promise.all([
        api.get(`/workspaces/${workspaceId.value}/permissions/me`),
        api.get(`/workspaces/${workspaceId.value}/members`, {
          params: {
            page: requestPage,
            page_size: MEMBER_PAGE_SIZE,
            keyword: requestKeyword || undefined,
          },
        }),
      ])
  
      const payload = (membersRes.data || {}) as WorkspaceMemberListPayload
      myPermissionPayload.value = permissionRes.data
      ownerMember.value = payload.owner || null
      members.value = payload.items || []
      memberTotal.value = Number(payload.total || 0)
      memberPage.value = Number(payload.page || requestPage)
      memberKeywordQuery.value = requestKeyword
  
      const maxPage = Math.max(1, Math.ceil(memberTotal.value / MEMBER_PAGE_SIZE))
      if (memberPage.value > maxPage) {
        await loadMembers({ page: maxPage, keyword: requestKeyword })
        return
      }
  
      seedMemberDrafts()
      seedPermissionExpandState()
    } catch (error) {
      membersError.value = formatApiError(error, t('settings.members.load_failed'), t)
    } finally {
      loadingMembers.value = false
    }
  }
  
  const runMemberSearch = async () => {
    await loadMembers({ page: 1, keyword: memberKeywordInput.value })
  }
  
  const clearMemberSearch = async () => {
    memberKeywordInput.value = ''
    await loadMembers({ page: 1, keyword: '' })
  }
  
  const prevMemberPage = async () => {
    if (memberPage.value <= 1) return
    await loadMembers({ page: memberPage.value - 1 })
  }
  
  const nextMemberPage = async () => {
    if (memberPage.value >= totalMemberPages.value) return
    await loadMembers({ page: memberPage.value + 1 })
  }
  
  const addMember = async () => {
    if (!workspaceId.value || !canManageMembers.value || !addForm.user_email.trim()) return
  
    addingMember.value = true
    membersError.value = ''
    try {
      await api.post(`/workspaces/${workspaceId.value}/members`, {
        user_email: addForm.user_email.trim(),
        role: addForm.role,
        is_expert: addForm.is_expert,
        permissions: addForm.permissions,
      })
  
      addForm.user_email = ''
      addForm.role = 'DEVELOPER'
      addForm.is_expert = false
      addForm.permissions = defaultPermissionsByRole('DEVELOPER')
  
      await loadMembers()
    } catch (error) {
      membersError.value = formatApiError(error, t('settings.members.add_failed'), t)
    } finally {
      addingMember.value = false
    }
  }
  
  const saveMember = async (member: WorkspaceMember) => {
    if (!workspaceId.value || !canManageMembers.value || member.is_owner) return
  
    const draft = getDraft(member)
    savingMemberId.value = member.id
    membersError.value = ''
    try {
      await api.put(`/workspaces/${workspaceId.value}/members/${member.id}`, {
        role: draft.role,
        is_expert: draft.is_expert,
        permissions: draft.permissions,
      })
      await loadMembers()
    } catch (error) {
      membersError.value = formatApiError(error, t('settings.members.save_failed'), t)
    } finally {
      savingMemberId.value = ''
    }
  }
  
  const askRemoveMember = (member: WorkspaceMember) => {
    if (!canManageMembers.value || member.is_owner) return
    memberToRemove.value = member
    showRemoveConfirm.value = true
  }
  
  const closeRemoveDialog = () => {
    if (removingMemberId.value) return
    showRemoveConfirm.value = false
    memberToRemove.value = null
  }
  
  const confirmRemoveMember = async () => {
    if (!workspaceId.value || !memberToRemove.value) return
  
    removingMemberId.value = memberToRemove.value.id
    membersError.value = ''
    try {
      await api.delete(`/workspaces/${workspaceId.value}/members/${memberToRemove.value.id}`)
      showRemoveConfirm.value = false
      memberToRemove.value = null
      await loadMembers()
    } catch (error) {
      membersError.value = formatApiError(error, t('settings.members.remove_failed'), t)
    } finally {
      removingMemberId.value = ''
    }
  }
  
  onMounted(async () => {
    if (!authStore.user) {
      await authStore.fetchCurrentUser()
    }
    loadAppearanceStateFromUser()
    await loadMembers()
  })
  
  watch(workspaceId, async (next, prev) => {
    if (!next || next === prev) return
    memberPage.value = 1
    memberKeywordInput.value = ''
    memberKeywordQuery.value = ''
    await loadMembers()
  })
  
  watch(() => authStore.user?.avatar_svg, (next) => {
    if (!next?.trim()) return
    if (!uploadedSvg.value.trim()) {
      uploadedSvg.value = next
    }
  })

  return {
    activeSection,
    addForm,
    addingMember,
    addMember,
    appearanceError,
    appearanceSuccess,
    applyDraftRoleDefaults,
    askRemoveMember,
    authStore,
    avatarMode,
    avatarSaving,
    avatarTemplateColor,
    avatarTemplateOptions,
    avatarTemplateStyle,
    canManageMembers,
    changeLanguage,
    clearAppearanceMessage,
    clearMemberSearch,
    closeRemoveDialog,
    confirmRemoveMember,
    createEmptyPermissions,
    currentLang,
    defaultPermissionsByRole,
    enabledPermissionCount,
    getDraft,
    handleAvatarFileChange,
    isAvatarSvgValidationError,
    isPermissionExpanded,
    loadAppearanceStateFromUser,
    loadingMembers,
    loadMembers,
    locale,
    MEMBER_PAGE_SIZE,
    memberDrafts,
    memberKeywordInput,
    memberKeywordQuery,
    memberPage,
    memberPermissionExpanded,
    memberRoleOptions,
    members,
    membersError,
    memberToRemove,
    memberTotal,
    myPermissionPayload,
    nextMemberPage,
    ownerMember,
    permissionOptionCount,
    permissionOptions,
    previewAvatarSvg,
    previewAvatarUrl,
    prevMemberPage,
    removingMemberId,
    resetAddFormByRole,
    roleTag,
    route,
    runMemberSearch,
    saveAvatarPreference,
    saveMember,
    savingMemberId,
    seedMemberDrafts,
    seedPermissionExpandState,
    settingsSections,
    showRemoveConfirm,
    t,
    togglePermissionExpanded,
    totalMemberCount,
    totalMemberPages,
    uploadedFileName,
    uploadedSvg,
    uploadedSvgPreviewUrl,
    workspaceId,
  }
}

export type SettingsViewModel = ReturnType<typeof useSettingsViewModel>
