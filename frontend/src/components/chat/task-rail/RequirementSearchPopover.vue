<script setup lang="ts">
import { computed, nextTick, onMounted, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search, Star, X } from '@/components/icons'
import { useRequirementSearch } from '@/composables/useRequirementSearch'
import { requirementLabel, type RequirementOption } from '@/types/taskRail'

const props = defineProps<{ workspaceId: string; pinnedIds: string[]; anchor: { left: number; top: number } }>()
const emit = defineEmits<{ close: []; select: [requirement: RequirementOption]; pin: [requirement: RequirementOption] }>()
const { t } = useI18n()
const search = useRequirementSearch(() => props.workspaceId, () => true)
const input = useTemplateRef<HTMLInputElement>('queryInput')
const position = computed(() => ({
  left: `${Math.max(8, Math.min(props.anchor.left, window.innerWidth - 376))}px`,
  top: `${Math.max(8, Math.min(props.anchor.top, window.innerHeight - 460))}px`,
}))
onMounted(async () => { await nextTick(); input.value?.focus() })
function scroll(event: Event) {
  const target = event.target as HTMLElement
  if (target.scrollTop + target.clientHeight >= target.scrollHeight - 30) void search.search(false)
}
</script>

<template>
  <Teleport to="body">
    <div class="requirement-search-overlay" @mousedown.self="emit('close')" @keydown.esc.stop.prevent="emit('close')">
      <section class="requirement-search-popover" :style="position" role="dialog" :aria-label="t('task_rail.more')">
        <header class="search-head"><strong>{{ t('task_rail.more') }}</strong><button type="button" :aria-label="t('common.cancel')" @click="emit('close')"><X class="w-4 h-4" /></button></header>
        <label class="search-input"><Search class="w-4 h-4" /><input ref="queryInput" v-model="search.query.value" :placeholder="t('task_rail.search_placeholder')" :aria-label="t('task_rail.search_placeholder')" /></label>
        <div class="search-results" @scroll="scroll">
          <div v-for="item in search.items.value" :key="item.id" class="result-row">
            <button type="button" class="result-select" @click="emit('select', item)"><strong>{{ requirementLabel(item) }}</strong><span v-if="item.parent_title">{{ item.parent_title }}</span><small>{{ item.status }}</small></button>
            <button type="button" class="pin-btn" :class="{ pinned: pinnedIds.includes(item.id) }" :title="t(pinnedIds.includes(item.id) ? 'task_rail.unpin' : 'task_rail.pin')" :aria-label="t(pinnedIds.includes(item.id) ? 'task_rail.unpin' : 'task_rail.pin')" :aria-pressed="pinnedIds.includes(item.id)" @click="emit('pin', item)"><Star class="w-4 h-4" :fill="pinnedIds.includes(item.id) ? 'currentColor' : 'none'" /></button>
          </div>
          <p v-if="search.loading.value" class="search-feedback" role="status">{{ t('common.loading') }}</p>
          <button v-else-if="search.error.value" type="button" class="search-feedback retry" @click="search.search()">{{ t('task_rail.retry') }}</button>
          <p v-else-if="!search.items.value.length" class="search-feedback">{{ t('task_rail.no_requirements') }}</p>
          <button v-else-if="search.items.value.length < search.total.value" type="button" class="search-feedback retry" @click="search.search(false)">{{ t('task_rail.load_more') }}</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.requirement-search-overlay { position:fixed; inset:0; z-index:1100; }
.requirement-search-popover { position:absolute; width:360px; max-width:calc(100vw - 16px); background:var(--color-surface-white); border:1px solid var(--color-primary-100); border-radius:12px; box-shadow:0 12px 40px rgba(15,23,42,.16); padding:12px; box-sizing:border-box; animation:search-enter .15s ease-out; }
.search-head { display:flex; justify-content:space-between; align-items:center; font-size:0.875rem; margin-bottom:12px; }
.search-head button, .pin-btn { display:flex; align-items:center; justify-content:center; background:transparent; border:0; color:var(--color-text-muted); padding:6px; border-radius:6px; cursor:pointer; }
.search-input { display:flex; align-items:center; gap:8px; border:1px solid var(--color-primary-100); border-radius:8px; padding:8px 10px; color:var(--color-text-muted); }
.search-input input { flex:1; min-width:0; border:0; outline:none; background:transparent; font:inherit; font-size:.8rem; }
.search-results { max-height:min(340px, calc(100vh - 160px)); overflow-y:auto; margin-top:8px; }
.result-row { display:flex; align-items:center; gap:8px; border-radius:8px; }
.result-row:hover { background:var(--color-primary-50); }
.result-select { display:grid; gap:3px; flex:1; min-width:0; padding:10px; border:0; background:transparent; text-align:left; cursor:pointer; color:var(--color-text-body); font:inherit; }
.result-select strong, .result-select span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.8rem; }
.result-select span, .result-select small { font-size:.72rem; color:var(--color-text-muted); }
.pin-btn.pinned { color:var(--color-primary-600); }
.search-feedback { display:block; width:100%; text-align:center; padding:12px 0; font-size:.8rem; color:var(--color-text-muted); }
.retry { background:transparent; border:0; cursor:pointer; }
@keyframes search-enter { from { opacity:0; transform:translateX(-5px) } to { opacity:1; transform:translateX(0) } }
@media (prefers-reduced-motion:reduce) { .requirement-search-popover { animation:none; } }
</style>
