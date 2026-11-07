import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { isDesktop } from '@/utils/runtime'

const router = createRouter({
  history: isDesktop()
    ? createWebHashHistory()
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
      name: 'login',
      component: () => import('../views/LoginView.vue')
    },
    // 链接邀请加入页（免登录打开；接受时要求登录）
    {
      path: '/join/:token',
      name: 'joinInvite',
      component: () => import('../views/JoinInviteView.vue')
    },
    // 任务会话免登录分享页（令牌在 fragment；READ 只读 / INPUT 邀请输入）
    {
      path: '/share/session',
      name: 'sharedTaskSession',
      component: () => import('../views/SharedTaskSessionView.vue')
    },
    // OAuth 三方登录流程页（免鉴权；后端 302 落地页，T04）
    {
      path: '/oauth/callback',
      name: 'oauthCallback',
      component: () => import('../views/OAuthCallbackView.vue')
    },
    {
      path: '/oauth/register',
      name: 'oauthRegister',
      component: () => import('../views/OAuthRegisterView.vue')
    },
    {
      path: '/oauth/bind-confirm',
      name: 'oauthBindConfirm',
      component: () => import('../views/OAuthBindConfirmView.vue')
    },
    {
      path: '/settings',
      name: 'userSettings',
      component: () => import('../views/UserSettingsView.vue'),
      meta: { requiresAuth: true }
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
    // Legacy URLs kept working: centers are now organized as /config (configuration)
    // and /ops (operations & management).
    {
      path: '/skills',
      redirect: '/config/skills',
    },
    {
      path: '/skills/:pathMatch(.*)*',
      redirect: (to) => ({
        path: `/config/skills/${(to.params.pathMatch as string[]).join('/')}`,
        query: to.query,
        hash: to.hash,
      }),
    },
    {
      path: '/management/:pathMatch(.*)*',
      redirect: (to) => {
        const rest = (to.params.pathMatch as string[]).join('/')
        return {
          path: rest ? `/config/${rest}` : '/config',
          query: to.query,
          hash: to.hash,
        }
      },
    },
    {
      path: '/ops/skills/:pathMatch(.*)*',
      redirect: (to) => {
        const rest = (to.params.pathMatch as string[]).join('/')
        return {
          path: rest ? `/config/skills/${rest}` : '/config/skills',
          query: to.query,
          hash: to.hash,
        }
      },
    },
    {
      // 配置中心：产品 / 项目 / 仓库 / 技能 / 系统等“配置类”能力。
      path: '/config',
      component: () => import('../views/layouts/CenterLayout.vue'),
      meta: { requiresAuth: true, center: 'config' },
      children: [
        {
          path: 'products',
          name: 'productsHome',
          component: () => import('../views/config/ProductsView.vue'),
        },
        {
          path: 'products/:productId',
          name: 'productDetail',
          component: () => import('../views/config/ProductDetailView.vue'),
        },
        {
          path: 'projects',
          name: 'projectsHome',
          component: () => import('../views/config/ProjectsView.vue'),
        },
        {
          path: 'projects/:projectId',
          name: 'projectDetail',
          component: () => import('../views/config/ProjectDetailView.vue'),
        },
        {
          path: 'repositories',
          name: 'repositoriesHome',
          component: () => import('../views/config/RepositoriesView.vue'),
        },
        {
          path: 'skills',
          name: 'skillsHome',
          component: () => import('../views/config/SkillsView.vue'),
        },
        {
          path: 'skills/new',
          name: 'skillsCreate',
          component: () => import('../views/config/SkillEditorView.vue'),
        },
        {
          path: 'skills/:skillId/edit',
          name: 'skillsEdit',
          component: () => import('../views/config/SkillEditorView.vue'),
        },
        {
          path: 'skills/:skillId/edit/analysis',
          name: 'skillsEditAnalysis',
          component: () => import('../views/config/SkillEditorView.vue'),
        },
        {
          path: 'skills/:skillId/edit/analysis/risks/:riskKey',
          name: 'skillsEditAnalysisRisk',
          component: () => import('../views/config/SkillEditorView.vue'),
        },
        {
          path: 'system',
          name: 'systemConfigHome',
          component: () => import('../views/config/SystemConfigView.vue'),
        },
        {
          path: 'system/:feature',
          name: 'systemConfigDetail',
          component: () => import('../views/config/SystemConfigDetailView.vue'),
        },
        {
          path: '',
          redirect: '/config/products',
        },
      ],
    },
    {
      // 管理中心：队列运维 / 案例同步队列等“运维管理类”能力。
      path: '/ops',
      component: () => import('../views/layouts/CenterLayout.vue'),
      meta: { requiresAuth: true, center: 'ops' },
      children: [
        {
          path: 'queue',
          name: 'opsQueueList',
          component: () => import('../views/ops/OpsQueueListView.vue'),
        },
        {
          path: 'queue/:source/:jobId',
          name: 'opsQueueDetail',
          component: () => import('../views/ops/OpsQueueDetailView.vue'),
        },
        {
          path: 'rag-queue',
          name: 'ragQueueList',
          component: () => import('../views/ops/RagQueueView.vue'),
        },
        {
          path: 'rag-queue/:queueId',
          name: 'ragQueueDetail',
          component: () => import('../views/ops/RagQueueDetailView.vue'),
        },
        {
          path: '',
          redirect: '/ops/queue',
        },
      ],
    },
    {
      path: '/knowledge',
      component: () => import('../views/layouts/CenterLayout.vue'),
      meta: { requiresAuth: true, center: 'knowledge' },
      children: [
        {
          path: 'business',
          name: 'knowledgeBusiness',
          component: () => import('../views/knowledge/BusinessKnowledgeView.vue'),
        },
        {
          path: 'framework',
          name: 'knowledgeFramework',
          component: () => import('../views/knowledge/FrameworkKnowledgeView.vue'),
        },
        {
          path: 'maintenance',
          name: 'knowledgeMaintenance',
          component: () => import('../views/knowledge/MaintenanceKnowledgeView.vue'),
        },
        {
          path: 'cases',
          name: 'knowledgeCases',
          component: () => import('../views/knowledge/KnowledgeCaseCenterView.vue'),
        },
        {
          path: 'cases/:wsId',
          name: 'knowledgeCasesWorkspace',
          component: () => import('../views/knowledge/KnowledgeCaseCenterView.vue'),
        },
        {
          path: 'cases/:wsId/:caseId',
          name: 'knowledgeCaseDetail',
          component: () => import('../views/CaseReportView.vue'),
        },
        {
          path: 'cases/:wsId/playbooks/:playbookId',
          name: 'knowledgePlaybookDetail',
          component: () => import('../views/PlaybookDetailView.vue'),
        },
        {
          path: 'cases/:wsId/promotions/:jobId',
          name: 'knowledgeCasePromotionReview',
          component: () => import('../views/CasePromotionReviewView.vue'),
        },
        {
          path: '',
          redirect: '/knowledge/business',
        },
      ],
    },
    {
      // 注意：前端页面路由不要使用 /ws 前缀，该前缀被后端 WebSocket 代理（vite proxy / nginx）占用，
      // 整页刷新 / 直达链接会被代理转发到后端 API 导致 404。
      path: '/workspaces/:wsId',
      component: () => import('../views/layouts/WorkspaceLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('../views/DashboardView.vue')
        },
        {
          path: 'chat/:taskId/spec',
          name: 'taskSpec',
          component: () => import('../views/TaskSpecView.vue')
        },
        {
          path: 'chat/:taskId?',
          name: 'taskChat',
          component: () => import('../views/ChatView.vue')
        },
        {
          path: 'chat',
          name: 'chat',
          redirect: (to) => ({
            name: 'taskChat',
            params: { wsId: to.params.wsId },
            query: to.query,
            hash: to.hash,
          }),
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
          path: 'assets/requirements/:requirementId/split-review/:batchId',
          name: 'workspaceAssetRequirementSplitReview',
          component: () => import('../views/WorkspaceAssetRequirementSplitReviewView.vue')
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
          path: 'cases',
          name: 'workspaceCases',
          component: () => import('../views/CaseCenterView.vue')
        },
        {
          path: 'cases/:caseId',
          name: 'workspaceCaseDetail',
          component: () => import('../views/CaseReportView.vue')
        },
        {
          path: 'cases/playbooks/:playbookId',
          name: 'workspacePlaybookDetail',
          alias: 'playbooks/:playbookId',
          component: () => import('../views/PlaybookDetailView.vue')
        },
        {
          path: 'cases/promotions/:jobId',
          name: 'workspaceCasePromotionReview',
          component: () => import('../views/CasePromotionReviewView.vue')
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

  // 配置项：关闭“项目管理/产品管理”选择功能时，屏蔽对应功能页面。
  if (
    to.name === 'productsHome' ||
    to.name === 'productDetail' ||
    to.name === 'projectsHome' ||
    to.name === 'projectDetail'
  ) {
    const { useSystemConfigStore } = await import('@/stores/systemConfig')
    const systemConfigStore = useSystemConfigStore()
    await systemConfigStore.load()
    if (!systemConfigStore.projectProductManagementEnabled) {
      return { path: '/config/repositories' }
    }
  }

  return true
})

export default router
