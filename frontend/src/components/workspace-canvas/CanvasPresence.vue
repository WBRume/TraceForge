<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { CanvasViewer } from './model'

const props = defineProps<{ viewers: CanvasViewer[] }>()
const { t } = useI18n()
const visibleLimit = 5
const visibleViewers = computed(() => props.viewers.slice(0, visibleLimit))
const remainingViewers = computed(() => props.viewers.slice(visibleLimit))
</script>

<template>
  <ul v-if="viewers.length" class="canvas-presence" data-testid="canvas-presence"
    :aria-label="t('workspace_canvas.presence.online', { count: viewers.length })">
    <li v-for="viewer in visibleViewers" :key="viewer.id" :data-viewer-id="viewer.id">
      <UserAvatar :user-id="viewer.id" :display-name="viewer.display_name" :avatar-url="viewer.avatar_url"
        :avatar-svg="viewer.avatar_svg" :title="viewer.display_name" size="md" />
    </li>
    <li v-if="remainingViewers.length">
      <el-popover trigger="click" placement="bottom-end" :width="236">
        <template #reference>
          <button type="button" class="presence-more"
            :aria-label="t('workspace_canvas.presence.more', { count: remainingViewers.length })">+{{ remainingViewers.length }}</button>
        </template>
        <ul class="presence-overflow">
          <li v-for="viewer in remainingViewers" :key="viewer.id" :data-viewer-id="viewer.id">
            <UserAvatar :user-id="viewer.id" :display-name="viewer.display_name" :avatar-url="viewer.avatar_url"
              :avatar-svg="viewer.avatar_svg" size="sm" />
            <span>{{ viewer.display_name }}</span>
          </li>
        </ul>
      </el-popover>
    </li>
  </ul>
</template>

<style scoped>
.canvas-presence, .presence-overflow { margin: 0; padding: 0; list-style: none; }
.canvas-presence { display: flex; align-items: center; gap: 5px; }
.canvas-presence li { display: flex; align-items: center; }
.presence-more {
  display: inline-grid;
  place-items: center;
  min-width: 29px;
  height: 29px;
  padding: 0 5px;
  border: 1px solid #e2e8f0;
  border-radius: 50%;
  background: #f8fafc;
  color: #475569;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.presence-more:hover, .presence-more:focus-visible { background: #f0f9ff; color: #0369a1; }
.presence-overflow { display: grid; gap: 8px; max-height: 240px; overflow: auto; }
.presence-overflow li { display: flex; align-items: center; gap: 8px; overflow-wrap: anywhere; }
</style>
