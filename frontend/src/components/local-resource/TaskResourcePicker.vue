<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Laptop, Server } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import api from '@/utils/api'
import { useLocalResources, type TaskExecution } from '@/composables/useLocalResources'

const props = defineProps<{ workspaceId: string }>()
const emit = defineEmits<{ change: [value: TaskExecution] }>()

const { items, enabled, error, load } = useLocalResources(() => props.workspaceId)
type ExecutionMode = 'SERVER' | 'LOCAL'
const mode = ref<ExecutionMode>('SERVER')
const selectedResourceId = ref('')
const backend = ref('')

const available = computed(() => (items.value ?? []).filter(r => r.backend === backend.value))
const localEnabled = computed(() => enabled.value && available.value.length > 0)
const resourceOptions = computed(() => available.value.map(resource => ({ label: resource.name, value: resource.id })))

function emitCurrent() {
  if (mode.value === 'LOCAL') {
    const item = available.value.find(r => r.id === selectedResourceId.value)
    if (item) {
      emit('change', { location: 'LOCAL', resource_id: item.id, profile_revision: item.profile_revision })
      return
    }
  }
  emit('change', { location: 'SERVER' })
}

function selectMode(next: ExecutionMode) {
  if (next === 'LOCAL' && !localEnabled.value) return
  mode.value = next
  if (next === 'LOCAL' && !selectedResourceId.value) {
    selectedResourceId.value = available.value[0]?.id ?? ''
  }
  emitCurrent()
}

function chooseResource(value: unknown) {
  selectedResourceId.value = String(value ?? '')
  emitCurrent()
}

watch(() => props.workspaceId, async () => {
  mode.value = 'SERVER'
  selectedResourceId.value = ''
  emit('change', { location: 'SERVER' })
  await load()
  try { backend.value = (await api.get(`/workspaces/${props.workspaceId}/agent-backends`)).data.effective_agent_backend }
  catch { backend.value = '' }
}, { immediate: true })
</script>

<template>
  <div class="resource-picker">
    <div class="resource-picker-head">
      <div class="resource-picker-title-group">
        <span class="resource-picker-label">执行位置</span>
        <span class="resource-picker-hint">选择任务调度节点</span>
      </div>

      <!-- 执行位置分段复合控件 -->
      <div class="exec-seg" role="radiogroup" aria-label="执行位置">
        <!-- 服务器模式 -->
        <button
          type="button"
          class="exec-seg-item"
          :class="{ active: mode === 'SERVER' }"
          role="radio"
          :aria-checked="mode === 'SERVER'"
          @click="selectMode('SERVER')"
        >
          <Server class="w-3.5 h-3.5 seg-icon" />
          <span>服务器</span>
        </button>

        <!-- 本地模式：方案 C 行内复合下拉胶囊 -->
        <button
          type="button"
          class="exec-seg-item exec-seg-local"
          :class="{ active: mode === 'LOCAL', 'is-compound': mode === 'LOCAL' }"
          role="radio"
          :aria-checked="mode === 'LOCAL'"
          :disabled="mode !== 'LOCAL' && !localEnabled"
          :title="localEnabled ? '' : '当前工作区未配置可用的本地资源'"
          @click="selectMode('LOCAL')"
        >
          <Laptop class="w-3.5 h-3.5 seg-icon shrink-0" />
          <span v-if="mode !== 'LOCAL'">本地</span>

          <!-- 激活态：行内复合胶囊，集成原生 BaseSelect 样式的下拉框 -->
          <template v-else>
            <span class="status-indicator-dot" title="本地资源已就绪"></span>
            <span class="compound-label">本地:</span>
            <div class="compound-select-wrap" @click.stop>
              <BaseSelect
                :model-value="selectedResourceId"
                :options="resourceOptions"
                size="sm"
                class="compound-select"
                @update:model-value="chooseResource"
              />
            </div>
          </template>
        </button>
      </div>
    </div>

    <small v-if="error" class="resource-picker-error" role="status">{{ error }}</small>
  </div>
</template>

<style scoped>
.resource-picker {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.resource-picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 42px;
}

.resource-picker-title-group {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.resource-picker-label {
  color: #1e293b;
  font-size: 0.8125rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.resource-picker-hint {
  font-size: 0.72rem;
  color: #94a3b8;
  font-weight: 400;
}

@media (max-width: 480px) {
  .resource-picker-hint {
    display: none;
  }
}

/* 执行位置分段复合控件容器 */
.exec-seg {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px;
  border-radius: 10px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  box-shadow: inset 0 1px 1px rgba(0, 0, 0, 0.03);
}

/* 分段选项基础项 */
.exec-seg-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  font-family: inherit;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  user-select: none;
  box-sizing: border-box;
}

.exec-seg-item:hover:not(:disabled) {
  color: #0f172a;
}

/* 激活态（卡片微凸起） */
.exec-seg-item.active {
  background: #ffffff;
  color: #0284c7;
  border-color: rgba(226, 232, 240, 0.9);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.04);
}

.exec-seg-item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 复合行内胶囊形态（一体化卡片，消除多重边框） */
.exec-seg-item.is-compound {
  padding: 0 6px 0 10px;
  gap: 5px;
  cursor: default;
  border-color: rgba(14, 165, 233, 0.35);
  box-shadow: 0 1px 3px rgba(14, 165, 233, 0.12), 0 1px 2px rgba(15, 23, 42, 0.04);
}

.compound-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #0284c7;
}

/* 在线状态指示小绿点 */
.status-indicator-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 5px rgba(16, 185, 129, 0.6);
  flex-shrink: 0;
  animation: pulse-dot 2.5s infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.65; transform: scale(0.9); }
}

/* 复合胶囊内部 BaseSelect 容器：彻底去除内部独立边框与多余背景，与胶囊合二为一 */
.compound-select-wrap {
  width: auto;
  min-width: 100px;
  max-width: 200px;
  display: inline-flex;
  align-items: center;
}

:deep(.compound-select) {
  width: 100%;
}

/* 消除 BaseSelect 的内部重叠边框与背景，避免多重嵌套框 */
:deep(.compound-select .select-trigger) {
  height: 30px;
  padding: 0 2px;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
  gap: 4px;
}

/* 字体统一为科技蓝，消除生硬的纯黑 */
:deep(.compound-select .selected-text) {
  font-size: 0.75rem;
  font-weight: 600;
  color: #0284c7;
  letter-spacing: -0.01em;
  transition: color 0.15s ease;
}

:deep(.compound-select .select-trigger:hover .selected-text) {
  color: #0369a1;
}

/* 箭头颜色与整体蓝系呼应 */
:deep(.compound-select .select-arrow) {
  width: 0.85rem;
  height: 0.85rem;
  color: #0284c7;
  opacity: 0.85;
}

/* 下拉菜单面板保持原生 BaseSelect 的毛玻璃浮层面板 */
:deep(.compound-select .select-dropdown) {
  min-width: 200px;
  top: calc(100% + 6px);
  right: 0;
  left: auto;
  z-index: 1050;
  box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.12), 0 8px 10px -6px rgba(15, 23, 42, 0.08);
}

.resource-picker-error {
  color: #b91c1c;
  font-size: 0.75rem;
  margin-top: 2px;
}

/* 深色模式适配 */
:global(.dark) .resource-picker-label {
  color: #f1f5f9;
}

:global(.dark) .resource-picker-hint {
  color: #64748b;
}

:global(.dark) .exec-seg {
  background: rgba(30, 41, 59, 0.65);
  border-color: rgba(51, 65, 85, 0.6);
}

:global(.dark) .exec-seg-item {
  color: #94a3b8;
}

:global(.dark) .exec-seg-item:hover:not(:disabled) {
  color: #f8fafc;
}

:global(.dark) .exec-seg-item.active {
  background: #0f172a;
  color: #38bdf8;
  border-color: #334155;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
}

:global(.dark) .exec-seg-item.active.is-compound {
  border-color: rgba(56, 189, 248, 0.4);
}

:global(.dark) .compound-label {
  color: #38bdf8;
}

:global(.dark) :deep(.compound-select .selected-text) {
  color: #38bdf8;
}

:global(.dark) :deep(.compound-select .select-arrow) {
  color: #38bdf8;
}
</style>
