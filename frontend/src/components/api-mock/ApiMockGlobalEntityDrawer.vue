<script setup lang="ts">
import { ref } from 'vue'
import { X } from 'lucide-vue-next'
import EntityPanel from './EntityPanel.vue'
import type { ApiMockEntity } from '@/types/apiMock'

const props = defineProps<{
  open: boolean
  entities: ApiMockEntity[]
  canManage: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'create-entity', payload: { name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }): void
  (e: 'update-entity', payload: { id: string; row_version: number; name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }): void
  (e: 'delete-entity', entityId: string): void
}>()

const entityPanelRef = ref<InstanceType<typeof EntityPanel> | null>(null)

defineExpose({
  openCreateForm: () => {
    entityPanelRef.value?.openCreateForm('global')
  }
})
</script>

<template>
  <transition name="drawer-fade">
    <div v-if="open" class="drawer-shell" @click.self="emit('close')">
      <aside class="drawer-panel glass-panel" @click.stop>
        <header class="drawer-head">
          <div>
            <span class="drawer-kicker">{{ $t('api_mock.global_entities') || 'Global Entities' }}</span>
            <h2>{{ $t('api_mock.entity_manage_title') || 'Manage Entities' }}</h2>
          </div>
          <button type="button" class="icon-btn" @click="emit('close')">
            <X class="w-4 h-4" />
          </button>
        </header>

        <div class="drawer-body custom-scrollbar">
          <EntityPanel
            ref="entityPanelRef"
            style="border: none; background: transparent; padding: 0;"
            :entities="entities"
            :endpoint="null"
            :can-manage="canManage"
            @create-entity="emit('create-entity', $event)"
            @update-entity="emit('update-entity', $event)"
            @delete-entity="emit('delete-entity', $event)"
          />
        </div>
      </aside>
    </div>
  </transition>
</template>

<style scoped>
.drawer-shell {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  justify-content: flex-end;
  background: rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(6px);
}

.drawer-panel {
  width: min(34rem, calc(100vw - 1.25rem));
  height: 100%;
  border-radius: 24px 0 0 24px;
  border-right: none;
  background: #ffffff;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
}

.drawer-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.2rem 1.2rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}

.drawer-kicker {
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.drawer-head h2 {
  margin: 0.35rem 0 0;
}

.icon-btn {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.88);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.icon-btn:hover {
  background: #eff6ff;
  color: #0369a1;
}

.drawer-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 1rem 1.2rem;
}

.w-4 { width: 1rem; height: 1rem; }

.drawer-fade-enter-active,
.drawer-fade-leave-active {
  transition: opacity 0.22s ease;
}

.drawer-fade-enter-active .drawer-panel,
.drawer-fade-leave-active .drawer-panel {
  transition: transform 0.24s ease;
}

.drawer-fade-enter-from,
.drawer-fade-leave-to {
  opacity: 0;
}

.drawer-fade-enter-from .drawer-panel,
.drawer-fade-leave-to .drawer-panel {
  transform: translateX(1.5rem);
}
</style>
