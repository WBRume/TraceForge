import { markRaw, type Component } from 'vue'
import type { Router } from 'vue-router'
import {
  Box, Briefcase, ClipboardList, DocumentTextIcon, FolderKanban, GitFork, LayoutDashboard,
  LibraryBig, MessageSquare, Network, ServerCog, Settings, Users, Wrench,
} from '@/components/icons'
import type { WorkspaceTab } from '@/types/workspaceWindows'
import { isCanvasRoute } from '@/router/workspaceAssetPresentation'

export type DesktopTabTone = 'sky' | 'emerald' | 'violet' | 'amber' | 'teal' | 'slate'

export interface DesktopTabChoice {
  key: string
  path: string
  label: string
  icon: Component
  tone: DesktopTabTone
}

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

interface WorkspacePageSpec {
  name: keyof typeof labels
  tone: DesktopTabTone
}

const workspacePages: readonly WorkspacePageSpec[] = [
  { name: 'dashboard', tone: 'sky' },
  { name: 'taskChat', tone: 'emerald' },
  { name: 'workspaceAssetsRequirements', tone: 'violet' },
  { name: 'apiMock', tone: 'amber' },
  { name: 'workspaceMemberWorkload', tone: 'teal' },
  { name: 'settings', tone: 'slate' },
]

export function workspaceTabChoices(workspaceId: string, router: Router, t: (key: string) => string): DesktopTabChoice[] {
  return workspacePages.map(page => {
    const [key, icon] = labels[page.name]
    return {
      key: page.name,
      path: router.resolve({ name: page.name, params: { wsId: workspaceId } }).fullPath,
      label: t(key),
      icon: markRaw(icon),
      tone: page.tone,
    }
  })
}

export function workspaceOverviewChoice(router: Router, t: (key: string) => string): DesktopTabChoice {
  const [key, icon] = labels.workspaces
  return {
    key: 'workspaces',
    path: router.resolve({ name: 'workspaces', params: {} }).fullPath,
    label: t(key),
    icon: markRaw(icon),
    tone: 'sky',
  }
}

export function describeDesktopTab(tab: WorkspaceTab, router: Router, t: (key: string) => string) {
  const route = router.resolve(tab.path)
  const name = String(route.name ?? '')
  const item = isCanvasRoute(route) ? ['workspace_canvas.title', Box] as const : labels[name as keyof typeof labels]
    ?? (name.startsWith('workspaceAssetsRequirement') || name === 'workspaceAssetRequirementSplitReview' ? labels.workspaceAssetsRequirements
      : name.startsWith('workspaceAssetsTask') ? labels.workspaceAssetsTasks
      : name.startsWith('workspaceCase') || name.startsWith('workspacePlaybook') ? labels.workspaceCases
      : name.startsWith('skills') ? ['skills.entry', Wrench] as const
      : route.meta.center === 'ops' ? ['management.ops_layout_title', ServerCog] as const
      : route.meta.center === 'knowledge' ? ['knowledge.layout_title', LibraryBig] as const
      : labels.workspaces)
  return { ...tab, label: tab.title || t(item[0]), icon: markRaw(item[1]), workspaceId: typeof route.params.wsId === 'string' ? route.params.wsId : '' }
}

export type DesktopTab = ReturnType<typeof describeDesktopTab>
