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
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue')
    },
    {
      path: '/workspaces',
      name: 'workspaces',
      component: () => import('../views/WorkspaceView.vue'),
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
