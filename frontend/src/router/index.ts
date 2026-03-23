import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
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
          path: 'chat/:taskId',
          name: 'taskChat',
          component: () => import('../views/ChatView.vue')
        },
        {
          path: 'assets',
          name: 'assets',
          component: () => import('../views/AssetView.vue')
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
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else {
    next()
  }
})

export default router
