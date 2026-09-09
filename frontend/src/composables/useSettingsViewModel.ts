import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Bell, Bot, Languages, Link, MonitorCog, Palette, Shield, Users } from 'lucide-vue-next'
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

  type BatchAddResult = {
    email: string
    ok: boolean
    reason: string
  }

  type ParsedBatchEmail = {
    email: string
    state: 'ok' | 'duplicate' | 'invalid' | 'repeat'
  }

  type MemberViewFilter = 'all' | 'owner' | 'developer' | 'viewer' | 'expert'

  type InviteLinkItem = {
    id: string
    token: string
    role: string
    is_expert: boolean
    permissions: Record<string, boolean>
    max_uses: number | null
    used_count: number
    remaining_uses: number | null
    expires_at: string | null
    created_at: string
    status: string
    created_by_name: string
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
  
  // 服务端分页：与控制台表格的页码/分页器保持一致
  const MEMBER_PAGE_SIZE = 5
  
  const route = useRoute()
  const { locale, t } = useI18n()
  const authStore = useAuthStore()
  
  const currentLang = ref(locale.value)
  const activeSection = ref<string>('general')
  
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
  
  const batchAddInput = ref('')
  const batchAddRole = ref<'DEVELOPER' | 'VIEWER'>('DEVELOPER')
  const batchAddExpert = ref(false)
  const batchAddPermissions = ref<PermissionFlags>(defaultPermissionsByRole('DEVELOPER'))
  const batchAddRunning = ref(false)
  const batchAddDone = ref(false)
  const batchAddResults = ref<BatchAddResult[]>([])
  const showAddModal = ref(false)

  const memberViewFilter = ref<MemberViewFilter>('all')
  const selectedMemberIds = ref<Record<string, boolean>>({})
  const batchRoleValue = ref<'DEVELOPER' | 'VIEWER'>('DEVELOPER')
  const batchApplying = ref(false)
  const batchRemoving = ref(false)
  const showBatchRemoveConfirm = ref(false)

  const addModalTab = ref<'email' | 'link'>('email')
  const inviteLinks = ref<InviteLinkItem[]>([])
  const inviteLinksLoading = ref(false)
  const inviteLinkError = ref('')
  const inviteLinkCreating = ref(false)
  const revokingLinkId = ref('')
  const inviteLinkJustCreated = ref<InviteLinkItem | null>(null)
  const inviteLinkForm = ref({
    role: 'DEVELOPER' as 'DEVELOPER' | 'VIEWER',
    valid_days: 7,
    max_uses: 5,
    is_expert: false,
  })

  const BATCH_EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  
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
      id: 'connected_accounts',
      icon: Link,
      label: 'settings.connected_accounts.title',
      description: 'settings.connected_accounts.subtitle',
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
      id: 'agent',
      icon: Bot,
      label: 'settings.agent.title',
      description: 'settings.agent.subtitle',
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
  const consoleMembers = computed<WorkspaceMember[]>(() => {
    const list: WorkspaceMember[] = []
    if (ownerMember.value) list.push(ownerMember.value)
    list.push(...members.value)
    return list
  })
  const filteredConsoleMembers = computed(() => {
    switch (memberViewFilter.value) {
      case 'owner':
        return consoleMembers.value.filter(member => member.is_owner || member.role === 'OWNER')
      case 'developer':
        return consoleMembers.value.filter(member => !member.is_owner && member.role === 'DEVELOPER')
      case 'viewer':
        return consoleMembers.value.filter(member => !member.is_owner && member.role === 'VIEWER')
      case 'expert':
        return consoleMembers.value.filter(member => member.is_expert)
      default:
        return consoleMembers.value
    }
  })
  const memberViewCounts = computed(() => {
    const counts = { all: 0, owner: 0, developer: 0, viewer: 0, expert: 0 }
    for (const member of consoleMembers.value) {
      counts.all += 1
      if (member.is_owner || member.role === 'OWNER') {
        counts.owner += 1
      } else if (member.role === 'VIEWER') {
        counts.viewer += 1
      } else {
        counts.developer += 1
      }
      if (member.is_expert) counts.expert += 1
    }
    return counts
  })
  const selectableFilteredMembers = computed(() => filteredConsoleMembers.value.filter(member => !member.is_owner))
  const selectableFilteredCount = computed(() => selectableFilteredMembers.value.length)
  const allFilteredSelected = computed(() => (
    selectableFilteredCount.value > 0
    && selectableFilteredMembers.value.every(member => selectedMemberIds.value[member.id])
  ))
  const selectedMemberCount = computed(() => (
    consoleMembers.value.filter(member => !member.is_owner && selectedMemberIds.value[member.id]).length
  ))
  const selectedMembers = computed(() => (
    consoleMembers.value.filter(member => !member.is_owner && selectedMemberIds.value[member.id])
  ))
  const batchAddEmails = computed<ParsedBatchEmail[]>(() => {
    const seen = new Set<string>()
    const parsed: ParsedBatchEmail[] = []
    for (const raw of batchAddInput.value.split(/[\s,;，；]+/)) {
      const email = raw.trim().toLowerCase()
      if (!email) continue
      if (seen.has(email)) {
        parsed.push({ email, state: 'repeat' })
        continue
      }
      seen.add(email)
      if (consoleMembers.value.some(member => member.email.trim().toLowerCase() === email)) {
        parsed.push({ email, state: 'duplicate' })
      } else if (!BATCH_EMAIL_PATTERN.test(email)) {
        parsed.push({ email, state: 'invalid' })
      } else {
        parsed.push({ email, state: 'ok' })
      }
    }
    return parsed
  })
  const batchAddValidEmails = computed(() => batchAddEmails.value
    .filter(item => item.state === 'ok')
    .map(item => item.email))
  const batchAddBlockedCount = computed(() => batchAddEmails.value
    .filter(item => item.state !== 'ok')
    .length)
  const batchAddEnabledCount = computed(() => (
    permissionOptions.value.reduce((total, option) => total + (batchAddPermissions.value[option.key] ? 1 : 0), 0)
  ))
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
  
  watch(batchAddRole, () => {
    batchAddPermissions.value = defaultPermissionsByRole(batchAddRole.value)
  })

  const toggleMemberSelected = (memberId: string) => {
    selectedMemberIds.value = { ...selectedMemberIds.value, [memberId]: !selectedMemberIds.value[memberId] }
  }

  const isMemberSelected = (memberId: string) => Boolean(selectedMemberIds.value[memberId])

  const clearMemberSelection = () => {
    selectedMemberIds.value = {}
  }

  const toggleSelectAllFiltered = () => {
    const next: Record<string, boolean> = { ...selectedMemberIds.value }
    const shouldSelect = !allFilteredSelected.value
    for (const member of selectableFilteredMembers.value) {
      if (shouldSelect) {
        next[member.id] = true
      } else {
        delete next[member.id]
      }
    }
    selectedMemberIds.value = next
  }

  const toggleDraftExpert = (memberId: string) => {
    const draft = memberDrafts.value[memberId]
    if (draft) draft.is_expert = !draft.is_expert
  }

  const openAddModal = () => {
    if (!canManageMembers.value) return
    batchAddInput.value = ''
    batchAddRole.value = 'DEVELOPER'
    batchAddExpert.value = false
    batchAddPermissions.value = defaultPermissionsByRole('DEVELOPER')
    batchAddRunning.value = false
    batchAddDone.value = false
    batchAddResults.value = []
    showAddModal.value = true
    addModalTab.value = 'email'
    inviteLinkJustCreated.value = null
    loadInviteLinks()
  }

  const closeAddModal = () => {
    if (batchAddRunning.value) return
    showAddModal.value = false
  }

  const resetBatchAdd = () => {
    if (batchAddRunning.value) return
    batchAddInput.value = ''
    batchAddDone.value = false
    batchAddResults.value = []
  }

  const loadInviteLinks = async () => {
    if (!workspaceId.value || !canManageMembers.value) return
    inviteLinksLoading.value = true
    inviteLinkError.value = ''
    try {
      const res = await api.get(`/workspaces/${workspaceId.value}/invite-links`)
      inviteLinks.value = res.data?.items || []
    } catch (error) {
      inviteLinkError.value = formatApiError(error, t('settings.members.invite_link_load_failed'), t)
    } finally {
      inviteLinksLoading.value = false
    }
  }

  const createInviteLink = async () => {
    if (!workspaceId.value || !canManageMembers.value || inviteLinkCreating.value) return

    inviteLinkCreating.value = true
    inviteLinkError.value = ''
    try {
      const form = inviteLinkForm.value
      const res = await api.post(`/workspaces/${workspaceId.value}/invite-links`, {
        role: form.role,
        is_expert: form.is_expert,
        valid_days: form.valid_days,
        max_uses: form.max_uses,
      })
      inviteLinkJustCreated.value = res.data as InviteLinkItem
      await loadInviteLinks()
    } catch (error) {
      inviteLinkError.value = formatApiError(error, t('settings.members.invite_link_create_failed'), t)
    } finally {
      inviteLinkCreating.value = false
    }
  }

  const revokeInviteLink = async (link: InviteLinkItem) => {
    if (!workspaceId.value || revokingLinkId.value) return

    revokingLinkId.value = link.id
    inviteLinkError.value = ''
    try {
      await api.delete(`/workspaces/${workspaceId.value}/invite-links/${link.id}`)
      if (inviteLinkJustCreated.value?.id === link.id) {
        inviteLinkJustCreated.value = null
      }
      await loadInviteLinks()
    } catch (error) {
      inviteLinkError.value = formatApiError(error, t('settings.members.invite_link_revoke_failed'), t)
    } finally {
      revokingLinkId.value = ''
    }
  }

  const buildInviteJoinUrl = (token: string) => `${window.location.origin}/join/${token}`

  const copyInviteLinkUrl = async (token: string) => {
    try {
      await navigator.clipboard.writeText(buildInviteJoinUrl(token))
    } catch {
      /* 剪贴板不可用时静默失败，用户可手动选择链接文本复制 */
    }
  }
  
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
      clearMemberSelection()
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
  
  const runBatchAdd = async () => {
    if (!workspaceId.value || !canManageMembers.value || batchAddRunning.value) return

    const emails = batchAddValidEmails.value
    if (emails.length === 0) return

    batchAddRunning.value = true
    membersError.value = ''
    batchAddDone.value = false
    batchAddResults.value = []
    const results: BatchAddResult[] = []

    try {
      for (const email of emails) {
        try {
          await api.post(`/workspaces/${workspaceId.value}/members`, {
            user_email: email,
            role: batchAddRole.value,
            is_expert: batchAddExpert.value,
            permissions: batchAddPermissions.value,
          })
          results.push({ email, ok: true, reason: '' })
        } catch (error) {
          results.push({
            email,
            ok: false,
            reason: formatApiError(error, t('settings.members.add_failed'), t),
          })
        }
      }

      batchAddResults.value = results
      batchAddDone.value = true
      batchAddInput.value = ''
      await loadMembers()
    } finally {
      batchAddRunning.value = false
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
  
  const applyBatchRole = async () => {
    if (!workspaceId.value || !canManageMembers.value || batchApplying.value) return

    const targets = selectedMembers.value
    if (targets.length === 0) return

    batchApplying.value = true
    membersError.value = ''
    let failures = 0
    try {
      for (const member of targets) {
        try {
          await api.put(`/workspaces/${workspaceId.value}/members/${member.id}`, {
            role: batchRoleValue.value,
            is_expert: Boolean(member.is_expert),
            permissions: defaultPermissionsByRole(batchRoleValue.value),
          })
        } catch {
          failures += 1
        }
      }

      if (failures > 0) {
        membersError.value = t('settings.members.batch_partial_failed', { count: failures })
      }
      clearMemberSelection()
      await loadMembers()
    } finally {
      batchApplying.value = false
    }
  }

  const applyBatchExpert = async (expert: boolean) => {
    if (!workspaceId.value || !canManageMembers.value || batchApplying.value) return

    const targets = selectedMembers.value
    if (targets.length === 0) return

    batchApplying.value = true
    membersError.value = ''
    let failures = 0
    try {
      for (const member of targets) {
        try {
          await api.put(`/workspaces/${workspaceId.value}/members/${member.id}`, {
            role: member.role === 'VIEWER' ? 'VIEWER' : 'DEVELOPER',
            is_expert: expert,
            permissions: member.permissions,
          })
        } catch {
          failures += 1
        }
      }

      if (failures > 0) {
        membersError.value = t('settings.members.batch_partial_failed', { count: failures })
      }
      clearMemberSelection()
      await loadMembers()
    } finally {
      batchApplying.value = false
    }
  }

  const askRemoveSelectedMembers = () => {
    if (!canManageMembers.value || selectedMembers.value.length === 0) return
    showBatchRemoveConfirm.value = true
  }

  const closeBatchRemoveDialog = () => {
    if (batchRemoving.value) return
    showBatchRemoveConfirm.value = false
  }

  const confirmRemoveSelectedMembers = async () => {
    if (!workspaceId.value || !canManageMembers.value || batchRemoving.value) return

    const targets = selectedMembers.value
    if (targets.length === 0) return

    batchRemoving.value = true
    membersError.value = ''
    let failures = 0
    try {
      for (const member of targets) {
        try {
          await api.delete(`/workspaces/${workspaceId.value}/members/${member.id}`)
        } catch {
          failures += 1
        }
      }

      if (failures > 0) {
        membersError.value = t('settings.members.batch_partial_failed', { count: failures })
      }
      showBatchRemoveConfirm.value = false
      clearMemberSelection()
      await loadMembers()
    } finally {
      batchRemoving.value = false
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
    allFilteredSelected,
    addModalTab,
    applyBatchExpert,
    applyBatchRole,
    appearanceError,
    appearanceSuccess,
    applyDraftRoleDefaults,
    askRemoveMember,
    askRemoveSelectedMembers,
    authStore,
    avatarMode,
    avatarSaving,
    avatarTemplateColor,
    avatarTemplateOptions,
    avatarTemplateStyle,
    batchAddBlockedCount,
    batchAddDone,
    batchAddEmails,
    batchAddExpert,
    batchAddInput,
    batchAddEnabledCount,
    batchAddPermissions,
    batchAddResults,
    batchAddRole,
    batchAddRunning,
    batchAddValidEmails,
    batchApplying,
    batchRemoving,
    batchRoleValue,
    buildInviteJoinUrl,
    canManageMembers,
    changeLanguage,
    clearAppearanceMessage,
    clearMemberSearch,
    clearMemberSelection,
    closeAddModal,
    closeBatchRemoveDialog,
    closeRemoveDialog,
    confirmRemoveMember,
    confirmRemoveSelectedMembers,
    consoleMembers,
    copyInviteLinkUrl,
    createInviteLink,
    createEmptyPermissions,
    currentLang,
    defaultPermissionsByRole,
    enabledPermissionCount,
    filteredConsoleMembers,
    getDraft,
    handleAvatarFileChange,
    inviteLinkCreating,
    inviteLinkError,
    inviteLinkForm,
    inviteLinkJustCreated,
    inviteLinks,
    inviteLinksLoading,
    isAvatarSvgValidationError,
    isMemberSelected,
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
    memberViewCounts,
    memberViewFilter,
    myPermissionPayload,
    nextMemberPage,
    openAddModal,
    ownerMember,
    permissionOptionCount,
    permissionOptions,
    previewAvatarSvg,
    previewAvatarUrl,
    prevMemberPage,
    removingMemberId,
    resetBatchAdd,
    revokingLinkId,
    revokeInviteLink,
    roleTag,
    route,
    runBatchAdd,
    runMemberSearch,
    saveAvatarPreference,
    saveMember,
    savingMemberId,
    seedMemberDrafts,
    seedPermissionExpandState,
    selectableFilteredCount,
    selectedMemberCount,
    selectedMembers,
    settingsSections,
    showAddModal,
    showBatchRemoveConfirm,
    showRemoveConfirm,
    t,
    toggleDraftExpert,
    toggleMemberSelected,
    togglePermissionExpanded,
    toggleSelectAllFiltered,
    totalMemberCount,
    totalMemberPages,
    uploadedFileName,
    uploadedSvg,
    uploadedSvgPreviewUrl,
    workspaceId,
  }
}

export type SettingsViewModel = ReturnType<typeof useSettingsViewModel>
