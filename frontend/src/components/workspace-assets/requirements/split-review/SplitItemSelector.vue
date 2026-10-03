<script setup lang="ts">
import { Plus, Trash2 } from '@/components/icons'
import { getPriorityBadgeClass, type EditableSplitItem } from './model'
defineProps<{ items: EditableSplitItem[]; activeIndex: number; selectedCount: number; allSelected: boolean }>()
const emit = defineEmits<{ select: [index: number]; add: []; remove: [index: number]; include: [id: string, value: boolean]; selectAll: [value: boolean] }>()
</script>

<template>
<div class="sub-nav-bar-wrapper">
          <div class="sub-nav-bar-header">
            <label class="checkbox-label" title="全选 / 取消全选">
              <input :checked="allSelected" @change="emit('selectAll', ($event.target as HTMLInputElement).checked)" type="checkbox" />
              <span class="list-count-text">{{ selectedCount }} / {{ items.length }} 项将纳入需求库</span>
            </label>
            <button class="btn-add-sub" type="button" @click="emit('add')">
              <Plus class="w-3-5 h-3-5" />
              <span>新建子需求</span>
            </button>
          </div>

          <!-- 横向子需求卡片滑动栏 -->
          <div class="sub-cards-strip">
            <div
              v-for="(item, idx) in items"
              :key="item.item_id"
              class="strip-card"
              :class="{ active: idx === activeIndex }"
              @click="emit('select', idx)"
            >
              <div class="strip-card-top">
                <label class="card-checkbox-label" @click.stop>
                  <input :checked="item.include" @change="emit('include', item.item_id, ($event.target as HTMLInputElement).checked)" type="checkbox" />
                </label>
                <span class="card-seq-num">#{{ idx + 1 }}</span>
                <span class="card-priority-pill" :class="getPriorityBadgeClass(item.priority)">
                  {{ item.priority }}
                </span>
                <button
                  class="card-delete-btn"
                  type="button"
                  title="删除该子需求"
                  @click.stop="emit('remove', idx)"
                >
                  <Trash2 class="w-3-5 h-3-5" />
                </button>
              </div>

              <div class="strip-card-title" :title="item.title || '（未命名子需求）'">
                {{ item.title || '（未命名子需求）' }}
              </div>

              <div class="strip-card-footer">
                <span class="criteria-count-chip">
                  {{ item.acceptance_criteria.length }} 项准则
                </span>
              </div>
            </div>

            <div v-if="items.length === 0" class="strip-empty-hint">
              <span>暂无子需求条目</span>
            </div>
          </div>
        </div>
</template>

<style scoped>
.sub-nav-bar-wrapper {
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  padding: 14px 18px 12px;
  flex-shrink: 0;
}
.sub-nav-bar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.list-count-text {
  font-size: 0.82rem;
  color: #0284c7;
  font-weight: 700;
}
.btn-add-sub {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  background: #f0f9ff;
  color: #0284c7;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-add-sub:hover {
  background: #e0f2fe;
  border-color: #7dd3fc;
}
.sub-cards-strip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.sub-cards-strip::-webkit-scrollbar {
  height: 4px;
}
.sub-cards-strip::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}
.strip-card {
  flex: 0 0 210px;
  width: 210px;
  box-sizing: border-box;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.strip-card:hover {
  border-color: #94a3b8;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
}
.strip-card.active {
  background: #f0f9ff;
  border-color: #0ea5e9;
  box-shadow: 0 2px 10px rgba(14, 165, 233, 0.16);
}
.strip-card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.card-seq-num {
  font-size: 0.78rem;
  font-weight: 700;
  color: #64748b;
  font-family: var(--font-mono);
}
.card-priority-pill {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  text-transform: uppercase;
}
.card-priority-pill.priority-high { background: #fee2e2; color: #b91c1c; }
.card-priority-pill.priority-medium { background: #fef3c7; color: #b45309; }
.card-priority-pill.priority-low { background: #e0f2fe; color: #0369a1; }
.card-delete-btn {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  transition: all 0.2s ease;
}
.card-delete-btn:hover {
  color: #ef4444;
  background: #fee2e2;
}
.strip-card-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #0f172a;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}
.strip-card-footer {
  display: flex;
  align-items: center;
}
.criteria-count-chip {
  font-size: 0.7rem;
  font-weight: 600;
  color: #64748b;
  background: rgba(241, 245, 249, 0.8);
  padding: 1px 5px;
  border-radius: 4px;
}
.strip-empty-hint {
  padding: 10px;
  color: #94a3b8;
  font-size: 0.82rem;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  user-select: none;
}
.card-checkbox-label {
  display: flex;
  align-items: center;
}
.checkbox-label input[type="checkbox"],
.card-checkbox-label input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  margin: 0;
  border-radius: 4px;
  border: 1.5px solid #cbd5e1;
  background-color: #ffffff;
  background-repeat: no-repeat;
  background-position: center;
  background-size: 11px 11px;
  cursor: pointer;
  transition: all 0.16s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  outline: none;
  display: inline-block;
  vertical-align: middle;
}
.checkbox-label input[type="checkbox"]:hover:not(:disabled),
.card-checkbox-label input[type="checkbox"]:hover:not(:disabled) {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}
.checkbox-label input[type="checkbox"]:checked,
.card-checkbox-label input[type="checkbox"]:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.25);
}
.checkbox-label input[type="checkbox"]:checked:hover:not(:disabled),
.card-checkbox-label input[type="checkbox"]:checked:hover:not(:disabled) {
  border-color: #0284c7;
  background-color: #0284c7;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.35);
}
.checkbox-label input[type="checkbox"]:focus-visible,
.card-checkbox-label input[type="checkbox"]:focus-visible {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.22);
}
.w-3-5 { width: 14px; }
.h-3-5 { height: 14px; }
</style>
