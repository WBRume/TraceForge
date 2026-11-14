<script setup lang="ts">
defineProps<{ replacing: boolean; busy: boolean; canReplace: boolean }>()
defineEmits<{ 'update:replacing': [value: boolean] }>()
</script>

<template>
  <span class="agent-session-notice">
    <span role="status">{{ $t(replacing ? 'chat.agent_session_new_hint' : 'chat.agent_session_unavailable') }}</span>
    <button
      v-if="canReplace"
      type="button"
      class="session-action"
      :class="replacing ? 'btn-secondary' : 'btn-primary'"
      :disabled="busy"
      @click="$emit('update:replacing', !replacing)"
    >
      {{ $t(replacing ? 'common.cancel' : 'chat.agent_session_new') }}
    </button>
  </span>
</template>

<style scoped>
.agent-session-notice {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  color: inherit;
  font-size: 12px;
  line-height: 1.4;
}
.session-action {
  flex-shrink: 0;
  min-height: 24px;
  padding: 2px 8px;
  font-size: inherit;
  transition: background-color var(--transition-fast);
  white-space: nowrap;
}
.session-action.btn-primary {
  background-color: var(--color-primary-600);
  color: #fff;
}
.session-action.btn-primary:hover:not(:disabled) {
  background-color: var(--color-primary-700);
}
.session-action.btn-primary:hover {
  transform: none;
}
</style>
