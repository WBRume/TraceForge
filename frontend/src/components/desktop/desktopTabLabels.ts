import type { Router } from 'vue-router'
import {
  Box, Briefcase, ClipboardList, DocumentTextIcon, FolderKanban, GitFork, LayoutDashboard,
  LibraryBig, MessageSquare, Network, ServerCog, Settings, Users, Wrench,
} from '@/components/icons'
import type { WorkspaceTab } from '@/types/workspaceWindows'

const labels = {
  workspaces: ['workspaces.title', Briefcase],
  dashboard: ['layout.dashboard', LayoutDashboard],
  taskChat: ['layout.chat', MessageSquare],
  taskSpec: ['desktop_tabs.spec', DocumentTextIcon],
  workspaceMemberWorkload: ['workspace_assets.workload.title', Users],
  apiMock: ['layout.api_mock', Network],
  workspaceAssetsOverview: ['workspace_assets.sidebar_label', Box],
  workspaceAssetsRequirements: ['desktop_tabs.requirements', ClipboardList],
  workspaceAssetsTasks: ['desktop_tabs.tasks', MessageSquare],
  workspaceCases: ['layout.case_center', LibraryBig],
  workspaceAssetsKnowledgeBase: ['knowledge.layout_title', LibraryBig],
  deltaWorkbench: ['desktop_tabs.changes', GitFork],
  settings: ['common.settings', Settings],
  userSettings: ['common.settings', Settings],
  productsHome: ['management.nav_products', Box],
  productDetail: ['management.nav_products', Box],
  projectsHome: ['management.nav_projects', FolderKanban],
  projectDetail: ['management.nav_projects', FolderKanban],
  repositoriesHome: ['management.nav_repositories', GitFork],
  systemConfigHome: ['management.nav_system_config', Settings],
  systemConfigDetail: ['management.nav_system_config', Settings],
  provisioning: ['desktop_tabs.tasks', MessageSquare],
} as const

const workspacePages = ['dashboard', 'taskChat', 'workspaceAssetsRequirements', 'apiMock', 'workspaceMemberWorkload', 'settings'] as const

export function workspaceTabChoices(workspaceId: string, router: Router, t: (key: string) => string) {
  return [...workspacePages, 'workspaces' as const].map(name => {
    const [key, icon] = labels[name]
    const params = name === 'workspaces' ? {} : { wsId: workspaceId }
    return { path: router.resolve({ name, params }).fullPath, label: t(key), icon }
  })
}

export function describeDesktopTab(tab: WorkspaceTab, router: Router, t: (key: string) => string) {
  const route = router.resolve(tab.path)
  const name = String(route.name ?? '')
  const item = labels[name as keyof typeof labels]
    ?? (name.startsWith('workspaceAssetsRequirement') || name === 'workspaceAssetRequirementSplitReview' ? labels.workspaceAssetsRequirements
      : name.startsWith('workspaceAssetsTask') ? labels.workspaceAssetsTasks
      : name.startsWith('workspaceCase') || name.startsWith('workspacePlaybook') ? labels.workspaceCases
      : name.startsWith('skills') ? ['skills.entry', Wrench] as const
      : route.meta.center === 'ops' ? ['management.ops_layout_title', ServerCog] as const
      : route.meta.center === 'knowledge' ? ['knowledge.layout_title', LibraryBig] as const
      : labels.workspaces)
  return { ...tab, label: tab.title || t(item[0]), icon: item[1], workspaceId: typeof route.params.wsId === 'string' ? route.params.wsId : '' }
}

export type DesktopTab = ReturnType<typeof describeDesktopTab>
