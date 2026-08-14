import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { isElectron } from '@/utils/runtime'

const router = createRouter({
  history: isElectron()
    ? createWebHashHistory(import.meta.env.BASE_URL)
    : createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'portal',
      component: () => import('../views/PortalView.vue')
    },
    {
      path: '/docs',
      name: 'docs',
      component: () => import('../views/DocsView.vue')
    },
    {
      path: '/architecture',
      name: 'architecture',
      component: () => import('../views/ArchitectureView.vue')
    },
    {
      path: '/login',
      redirect: '/'
    },
    {
      path: '/workspaces',
      name: 'workspaces',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/desktop/:pathMatch(.*)*',
      redirect: '/workspaces',
    },
    {
      path: '/provisioning/:jobId',
      name: 'provisioning',
      component: () => import('../views/ProvisioningView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/ops/queue',
      name: 'opsQueueList',
      component: () => import('../views/OpsQueueListView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/ops/queue/:source/:jobId',
      name: 'opsQueueDetail',
      component: () => import('../views/OpsQueueDetailView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/skills',
      name: 'skillsHome',
      component: () => import('../views/SkillsView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/skills/new',
      name: 'skillsCreate',
      component: () => import('../views/SkillEditorView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/skills/:skillId/edit',
      name: 'skillsEdit',
      component: () => import('../views/SkillEditorView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/skills/:skillId/edit/analysis',
      name: 'skillsEditAnalysis',
      component: () => import('../views/SkillEditorView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/skills/:skillId/edit/analysis/risks/:riskKey',
      name: 'skillsEditAnalysisRisk',
      component: () => import('../views/SkillEditorView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/management',
      component: () => import('../views/management/ManagementLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: 'products',
          name: 'productsHome',
          component: () => import('../views/management/ProductsView.vue'),
        },
        {
          path: 'products/:productId',
          name: 'productDetail',
          component: () => import('../views/management/ProductDetailView.vue'),
        },
        {
          path: 'projects',
          name: 'projectsHome',
          component: () => import('../views/management/ProjectsView.vue'),
        },
        {
          path: 'projects/:projectId',
          name: 'projectDetail',
          component: () => import('../views/management/ProjectDetailView.vue'),
        },
        {
          path: 'repositories',
          name: 'repositoriesHome',
          component: () => import('../views/management/RepositoriesView.vue'),
        },
        {
          path: '',
          redirect: '/management/products',
        },
      ],
    },
    {
      path: '/ws/:wsId',
      component: () => import('../views/layouts/WorkspaceLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('../views/DashboardView.vue')
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('../views/ChatView.vue')
        },
        {
          path: 'chat/:taskId/spec',
          name: 'taskSpec',
          component: () => import('../views/TaskSpecView.vue')
        },
        {
          path: 'chat/:taskId',
          name: 'taskChat',
          component: () => import('../views/ChatView.vue')
        },
        {
          path: 'assets',
          name: 'workspaceAssetsOverview',
          component: () => import('../views/AssetView.vue')
        },
        {
          path: 'assets/requirements',
          name: 'workspaceAssetsRequirements',
          component: () => import('../views/AssetView.vue')
        },
        {
          path: 'assets/requirements/:requirementId',
          name: 'workspaceAssetsRequirementDetail',
          component: () => import('../views/WorkspaceAssetRequirementDetailView.vue')
        },
        {
          path: 'assets/tasks',
          name: 'workspaceAssetsTasks',
          component: () => import('../views/AssetView.vue')
        },
        {
          path: 'assets/tasks/:taskId/final-workflow',
          name: 'workspaceAssetsTaskFinalWorkflow',
          component: () => import('../views/WorkspaceAssetTaskFinalWorkflowView.vue')
        },
        {
          path: 'assets/tasks/:taskId',
          name: 'workspaceAssetTaskDetail',
          component: () => import('../views/WorkspaceAssetTaskDetailView.vue')
        },
        {
          path: 'assets/tasks/:taskId/deltas/:deltaId/workbench',
          name: 'deltaWorkbench',
          component: () => import('../views/DeltaWorkbenchView.vue')
        },
        {
          path: 'assets/traceability',
          name: 'workspaceAssetsTraceability',
          component: () => import('../views/AssetView.vue')
        },
        {
          path: 'assets/knowledge-base',
          name: 'workspaceAssetsKnowledgeBase',
          component: () => import('../views/AssetView.vue')
        },
        {
          path: 'api-mock',
          name: 'apiMock',
          component: () => import('../views/ApiMockWorkbenchView.vue')
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('../views/SettingsView.vue')
        }
      ]
    }
  ]
})

// Navigation Guard
router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  if (!to.meta.requiresAuth) return true

  if (!authStore.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (!authStore.user) {
    const me = await authStore.fetchCurrentUser()
    if (!me) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }

  return true
})

export default router
