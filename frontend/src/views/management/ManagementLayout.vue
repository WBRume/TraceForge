<!--
Management domain shell: navbar + sidebar navigation + router-view.
Route views stay thin; feature UI lives in components/management/*.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Package, FolderKanban, GitFork, ArrowLeft } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const routeName = computed(() => String(route.name ?? ''))

const navItems = computed(() => [
  {
    key: 'products',
    label: t('management.nav_products'),
    icon: Package,
    to: '/management/products',
    active: routeName.value === 'productsHome' || routeName.value === 'productDetail',
  },
  {
    key: 'projects',
    label: t('management.nav_projects'),
    icon: FolderKanban,
    to: '/management/projects',
    active: routeName.value === 'projectsHome' || routeName.value === 'projectDetail',
  },
  {
    key: 'repositories',
    label: t('management.nav_repositories'),
    icon: GitFork,
    to: '/management/repositories',
    active: routeName.value === 'repositoriesHome',
  },
])

const goBack = () => {
  router.push('/workspaces')
}
</script>

<template>
  <div class="mgmt-container">
    <nav class="mgmt-navbar">
      <div class="mgmt-logo">
        <div class="mgmt-logo-icon"></div>
        <router-link to="/" class="mgmt-logo-text">{{ $t('portal.title') }}</router-link>
        <span class="mgmt-subtitle">· {{ $t('management.layout_title') }}</span>
      </div>
      <div class="mgmt-nav-actions">
        <button class="btn-secondary flex items-center gap-2" @click="goBack">
          <ArrowLeft class="w-4 h-4" /> {{ $t('management.back_to_workspaces') }}
        </button>
      </div>
    </nav>

    <div class="mgmt-layout">
      <aside class="mgmt-sidebar glass-panel">
        <router-link
          v-for="item in navItems"
          :key="item.key"
          :to="item.to"
          class="mgmt-nav-item"
          :class="{ active: item.active }"
        >
          <component :is="item.icon" class="w-5 h-5" />
          <span>{{ item.label }}</span>
        </router-link>
      </aside>

      <main class="mgmt-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
