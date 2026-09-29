<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Settings2, ServerCog, LibraryBig } from '@/components/icons'

const router = useRouter()
const { t } = useI18n()

const isOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)
const triggerBtnRef = ref<HTMLElement | null>(null)

const toggleDropdown = () => {
  isOpen.value = !isOpen.value
}

const closeDropdown = () => {
  isOpen.value = false
}

const navigateTo = (path: string) => {
  closeDropdown()
  router.push(path)
}

const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as Node
  if (
    isOpen.value &&
    dropdownRef.value &&
    !dropdownRef.value.contains(target) &&
    triggerBtnRef.value &&
    !triggerBtnRef.value.contains(target)
  ) {
    closeDropdown()
  }
}

const handleKeyDown = (event: KeyboardEvent) => {
  if (event.key === 'Escape' && isOpen.value) {
    closeDropdown()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="app-switcher-container">
    <button
      ref="triggerBtnRef"
      type="button"
      class="app-switcher-trigger"
      :class="{ 'is-active': isOpen }"
      :title="t('management.layout_title') || '平台功能与服务中心'"
      aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="toggleDropdown"
    >
      <svg class="dots-grid-icon" viewBox="0 0 24 24" fill="currentColor">
        <circle cx="5" cy="5" r="2" />
        <circle cx="12" cy="5" r="2" />
        <circle cx="19" cy="5" r="2" />
        <circle cx="5" cy="12" r="2" />
        <circle cx="12" cy="12" r="2" />
        <circle cx="19" cy="12" r="2" />
        <circle cx="5" cy="19" r="2" />
        <circle cx="12" cy="19" r="2" />
        <circle cx="19" cy="19" r="2" />
      </svg>
    </button>

    <transition name="dropdown-pop">
      <div
        v-if="isOpen"
        ref="dropdownRef"
        class="app-switcher-menu"
        role="menu"
      >
        <div class="menu-header">
          <span class="menu-header-title">{{ t('management.entry_matrix_title') || '平台支撑与服务矩阵' }}</span>
        </div>

        <div class="menu-body">
          <!-- 配置中心 -->
          <div class="center-block center-config">
            <div class="center-row">
              <div class="center-identity">
                <div class="center-icon config-icon">
                  <Settings2 class="w-4 h-4" />
                </div>
                <span class="center-name">{{ t('management.entry_config_center') }}</span>
              </div>
              <button
                type="button"
                class="center-link-btn"
                @click="navigateTo('/management')"
              >
                {{ t('common.enter') || '主页' }} →
              </button>
            </div>
            <div class="sub-links-row">
              <button type="button" class="sub-tag-btn" @click="navigateTo('/management/products')">
                {{ t('management.nav_products') || '产品管理' }}
              </button>
              <button type="button" class="sub-tag-btn" @click="navigateTo('/management/projects')">
                {{ t('management.nav_projects') || '项目管理' }}
              </button>
              <button type="button" class="sub-tag-btn" @click="navigateTo('/management/repositories')">
                {{ t('management.nav_repositories') || '关联代码仓' }}
              </button>
              <button type="button" class="sub-tag-btn" @click="navigateTo('/management/system')">
                {{ t('management.nav_system_config') || '系统设置' }}
              </button>
            </div>
          </div>

          <!-- 管理中心 (运维与技能) -->
          <div class="center-block center-ops">
            <div class="center-row">
              <div class="center-identity">
                <div class="center-icon ops-icon">
                  <ServerCog class="w-4 h-4" />
                </div>
                <span class="center-name">{{ t('management.entry_ops_center') }}</span>
              </div>
              <button
                type="button"
                class="center-link-btn ops-link"
                @click="navigateTo('/ops')"
              >
                {{ t('common.enter') || '主页' }} →
              </button>
            </div>
            <div class="sub-links-row">
              <button type="button" class="sub-tag-btn" @click="navigateTo('/ops/queue')">
                {{ t('queue_ops.entry') || 'Ops 任务队列' }}
              </button>
              <button type="button" class="sub-tag-btn" @click="navigateTo('/ops/skills')">
                {{ t('skills.entry') || 'Skills 技能市场' }}
              </button>
              <button type="button" class="sub-tag-btn" @click="navigateTo('/ops/rag-queue')">
                {{ t('rag_queue.entry') || 'RAG 提取队列' }}
              </button>
            </div>
          </div>

          <!-- 知识中心 -->
          <div class="center-block center-knowledge">
            <div class="center-row">
              <div class="center-identity">
                <div class="center-icon knowledge-icon">
                  <LibraryBig class="w-4 h-4" />
                </div>
                <span class="center-name">{{ t('management.entry_knowledge_center') }}</span>
              </div>
              <button
                type="button"
                class="center-link-btn knowledge-link"
                @click="navigateTo('/knowledge')"
              >
                {{ t('common.enter') || '主页' }} →
              </button>
            </div>
            <div class="sub-links-row">
              <button type="button" class="sub-tag-btn" @click="navigateTo('/knowledge/business')">
                {{ t('knowledge.nav.business') }}
              </button>
              <button type="button" class="sub-tag-btn" @click="navigateTo('/knowledge/framework')">
                {{ t('knowledge.nav.framework') }}
              </button>
              <button type="button" class="sub-tag-btn" @click="navigateTo('/knowledge/cases')">
                {{ t('knowledge.nav.cases') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.app-switcher-container {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.app-switcher-trigger {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background-color: #ffffff;
  border: 1px solid #e2e8f0;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
}

.app-switcher-trigger:hover,
.app-switcher-trigger.is-active {
  background-color: #f0f9ff;
  border-color: #7dd3fc;
  color: #0284c7;
  box-shadow: 0 2px 6px -1px rgba(14, 165, 233, 0.15);
}

.dots-grid-icon {
  width: 16px;
  height: 16px;
  transition: transform 0.2s ease;
}

.app-switcher-trigger:hover .dots-grid-icon {
  transform: scale(1.08);
}

/* 下拉菜单面板 */
.app-switcher-menu {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  width: 384px;
  background: #ffffff;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.03);
  padding: 1rem;
  z-index: 1000;
}

.menu-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 0.5rem;
  margin-bottom: 0.75rem;
  border-bottom: 1px solid #f1f5f9;
}

.menu-header-title {
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
}

.menu-header-badge {
  font-size: 0.625rem;
  font-weight: 600;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  background: #f0f9ff;
  color: #0284c7;
  border: 1px solid #e0f2fe;
}

.menu-body {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.center-block {
  padding: 0.625rem 0.75rem;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  transition: all 0.2s ease;
}

.center-block:hover {
  background: #ffffff;
  box-shadow: 0 4px 12px -2px rgba(0, 0, 0, 0.04);
}

.center-config:hover {
  border-color: #bae6fd;
}
.center-ops:hover {
  border-color: #a7f3d0;
}
.center-knowledge:hover {
  border-color: #ddd6fe;
}

.center-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.375rem;
}

.center-identity {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.center-icon {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.config-icon {
  background: #e0f2fe;
  color: #0284c7;
}

.ops-icon {
  background: #dcfce7;
  color: #059669;
}

.knowledge-icon {
  background: #ede9fe;
  color: #7c3aed;
}

.center-name {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #1e293b;
}

.center-link-btn {
  background: none;
  border: none;
  font-size: 0.6875rem;
  font-weight: 600;
  color: #0284c7;
  cursor: pointer;
  padding: 0;
  transition: opacity 0.15s;
}

.center-link-btn:hover {
  opacity: 0.8;
  text-decoration: underline;
}

.ops-link { color: #059669; }
.knowledge-link { color: #7c3aed; }

.sub-links-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  padding-left: 2rem;
}

.sub-tag-btn {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 0.6875rem;
  font-weight: 500;
  padding: 0.125rem 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.sub-tag-btn:hover {
  color: #0284c7;
  border-color: #7dd3fc;
  background-color: #f0f9ff;
}

/* 动效 */
.dropdown-pop-enter-active,
.dropdown-pop-leave-active {
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.dropdown-pop-enter-from,
.dropdown-pop-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.97);
}
</style>
