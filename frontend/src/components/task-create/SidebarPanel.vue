<!-- SidebarPanel: 任务创建弹窗右侧滑出侧栏的共享框架。
     侧栏常驻 DOM，宽度 0 -> 440px 过渡展开，与弹窗 max-width 展开同步（等比例扩散感）；
     内容绝对定位填充，不参与高度计算，弹窗高度始终由表单决定，避免纵向跳动。
     Skills / 仓库两个侧栏经插槽注入标题、工具行、过滤行与内容区。 -->
<script setup lang="ts">
import { X } from 'lucide-vue-next'

defineProps<{
  open: boolean
  /** 标题行右侧的已选数量徽标文案 */
  badge: string
  badgeActive?: boolean
  subtitle?: string
}>()

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <aside class="modal-skills-sidebar" :class="{ open }">
    <div class="sidebar-inner">
      <div class="skills-sidebar-header">
        <div class="skills-sidebar-title-row">
          <slot name="title" />
          <div class="skills-header-actions">
            <span class="skills-selected-badge" :class="{ 'has-selected': badgeActive }">{{ badge }}</span>
            <button
              type="button"
              class="sidebar-close-btn"
              :title="$t('skills.task_panel.close_panel')"
              @click="emit('close')"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
        </div>
        <p v-if="subtitle" class="skills-sidebar-subtitle">{{ subtitle }}</p>
        <slot name="tools" />
        <slot name="filters" />
      </div>

      <slot name="notice" />

      <div class="skills-sidebar-body">
        <slot />
      </div>

      <footer v-if="$slots.footer" class="skills-pagination">
        <slot name="footer" />
      </footer>
    </div>
  </aside>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>
.modal-skills-sidebar {
  position: relative;
  width: 0;
  flex-shrink: 0;
  overflow: hidden;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.modal-skills-sidebar.open {
  width: 440px;
}

.sidebar-inner {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 440px;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  border-left: 1px solid #e2e8f0;
  box-shadow: -12px 0 32px rgba(15, 23, 42, 0.06);
  opacity: 0;
  transform: translateX(14px);
  transition: opacity 0.24s ease, transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}

.modal-skills-sidebar.open .sidebar-inner {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}

.skills-sidebar-header {
  padding: 1rem 1.25rem 0.75rem;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.skills-sidebar-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.skills-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.skills-selected-badge {
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-weight: 500;
}

.skills-selected-badge.has-selected {
  background: #0ea5e9;
  color: #ffffff;
  font-weight: 600;
}

.sidebar-close-btn {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
}

.sidebar-close-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.skills-sidebar-subtitle {
  margin: 0;
  font-size: 0.73rem;
  color: #64748b;
  line-height: 1.35;
}

.skills-sidebar-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skills-pagination {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid #f1f5f9;
  background: #ffffff;
  flex-shrink: 0;
}
</style>
