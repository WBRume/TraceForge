<script setup lang="ts">
const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <div v-if="show" class="overlay" @click.self="emit('close')">
    <div class="panel glass-panel">
      <header class="panel-head">
        <h3>{{ $t('api_mock.shortcuts_title') }}</h3>
        <button type="button" class="btn-secondary mini" @click="emit('close')">{{ $t('common.cancel') }}</button>
      </header>
      <ul class="list">
        <li><kbd>Ctrl/Cmd + K</kbd><span>{{ $t('api_mock.shortcut_search') }}</span></li>
        <li><kbd>Ctrl/Cmd + S</kbd><span>{{ $t('api_mock.shortcut_save_rule') }}</span></li>
        <li><kbd>Ctrl/Cmd + Shift + P</kbd><span>{{ $t('api_mock.shortcut_proxy_toggle') }}</span></li>
        <li><kbd>?</kbd><span>{{ $t('api_mock.shortcut_help') }}</span></li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 120;
}

.panel {
  width: min(560px, calc(100vw - 2rem));
  padding: 1rem;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.8rem;
}

.panel-head h3 {
  margin: 0;
  font-size: 1rem;
  color: #0f172a;
}

.mini {
  padding: 0.35rem 0.7rem;
  font-size: 0.78rem;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.list li {
  display: grid;
  grid-template-columns: 170px 1fr;
  gap: 0.6rem;
  align-items: center;
  padding: 0.45rem 0.55rem;
  border-radius: 10px;
  background: #f8fbff;
  border: 1px solid #dbeafe;
}

kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e2e8f0;
  border-bottom-width: 2px;
  border-radius: 8px;
  background: #fff;
  color: #0f172a;
  font-size: 0.74rem;
  font-weight: 700;
  padding: 0.3rem 0.5rem;
}

span {
  font-size: 0.82rem;
  color: #334155;
}
</style>
