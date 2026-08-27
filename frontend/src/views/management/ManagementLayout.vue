<!--
Knowledge/Management domain shell: navbar + sidebar navigation + router-view.
Serves centers distinguished by route meta.center:
  - 'config'    (配置中心 / Config Center): products / projects / repositories
  - 'ops'       (管理中心 / Management Center): queue ops / skills
  - 'knowledge' (知识中心 / Knowledge Center): business / framework / maintenance / cases
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Package, FolderKanban, GitFork, ServerCog, Wrench, BookMarked, Briefcase, Layers } from 'lucide-vue-next'
import AppSidebar from '@/components/AppSidebar.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const routeName = computed(() => String(route.name ?? ''))
const center = computed(() => String(route.meta.center || 'config'))

const isEditorRoute = computed(() =>
  ['skillsCreate', 'skillsEdit', 'skillsEditAnalysis', 'skillsEditAnalysisRisk'].includes(routeName.value))

const layoutTitle = computed(() => {
  if (center.value === 'ops') return t('management.ops_layout_title')
  if (center.value === 'knowledge') return t('knowledge.layout_title')
  return t('management.layout_title')
})

const configNavItems = computed(() => [
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

const opsNavItems = computed(() => [
  {
    key: 'queue',
    label: t('queue_ops.entry'),
    icon: ServerCog,
    to: '/ops/queue',
    active: routeName.value === 'opsQueueList' || routeName.value === 'opsQueueDetail',
  },
  {
    key: 'skills',
    label: t('skills.entry'),
    icon: Wrench,
    to: '/ops/skills',
    active: ['skillsHome', 'skillsCreate', 'skillsEdit', 'skillsEditAnalysis', 'skillsEditAnalysisRisk'].includes(routeName.value),
  },
  {
    key: 'rag-queue',
    label: t('rag_queue.entry'),
    icon: BookMarked,
    to: '/ops/rag-queue',
    active: routeName.value === 'ragQueueList' || routeName.value === 'ragQueueDetail',
  },
])

const knowledgeNavItems = computed(() => [
  {
    key: 'business',
    label: t('knowledge.nav.business'),
    icon: Briefcase,
    to: '/knowledge/business',
    active: routeName.value === 'knowledgeBusiness',
  },
  {
    key: 'framework',
    label: t('knowledge.nav.framework'),
    icon: Layers,
    to: '/knowledge/framework',
    active: routeName.value === 'knowledgeFramework',
  },
  {
    key: 'maintenance',
    label: t('knowledge.nav.maintenance'),
    icon: Wrench,
    to: '/knowledge/maintenance',
    active: routeName.value === 'knowledgeMaintenance',
  },
  {
    key: 'cases',
    label: t('knowledge.nav.cases'),
    icon: BookMarked,
    to: '/knowledge/cases',
    active: routeName.value === 'knowledgeCases' || routeName.value === 'knowledgeCasesWorkspace' || routeName.value === 'knowledgeCaseDetail',
  },
])

const navItems = computed(() => {
  if (center.value === 'ops') return opsNavItems.value
  if (center.value === 'knowledge') return knowledgeNavItems.value
  return configNavItems.value
})

const goBack = () => {
  router.push('/workspaces')
}
</script>

<template>
  <div class="mgmt-container">
    <AppSidebar
      :title="layoutTitle"
      :nav-items="navItems"
      :back-title="t('management.back_to_workspaces')"
      :collapsible="true"
      :default-collapsed="false"
      :show-back="true"
      :show-toggle="true"
      @back="goBack"
    />

    <main class="mgmt-content" :class="{ 'full-bleed': isEditorRoute }">
      <router-view />
    </main>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
