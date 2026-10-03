<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import { Loader2, Send, Save, AlertTriangle } from '@/components/icons'
import { formatApiError } from '@/utils/error'

const props = defineProps<{ scope: 'personal' | 'workspace'; workspaceId?: string }>()
const { t } = useI18n()

type Config = { enabled: boolean; url: string; delivery_location: string; events: string[] }
const defaults = (): Config => ({ enabled: false, url: '', delivery_location: 'server', events: ['AI_HITL_SUSPENDED', 'AI_RUN_FINISHED', 'AI_RUN_ERROR'] })
const config = ref(defaults())
const busy = ref(false)
const loading = ref(false)
const message = ref('')
const error = ref('')
let version = 0

const path = computed(() => props.scope === 'workspace' ? `/workspaces/${props.workspaceId}/task-webhook` : '/users/me/task-webhook')
const hasDesktopNative = computed(() => Boolean(window.sddDesktop?.webhooks))

const groups = computed(() => [
  {
    title: t('settings.webhook.group_runtime_title'),
    description: t('settings.webhook.group_runtime_desc'),
    items: [
      { value: 'AI_HITL_SUSPENDED', label: t('settings.webhook.event_hitl_suspended') },
      { value: 'AI_RUN_FINISHED', label: t('settings.webhook.event_run_finished') },
      { value: 'AI_RUN_ERROR', label: t('settings.webhook.event_run_error') },
      { value: 'AI_RUN_INTERRUPTED', label: t('settings.webhook.event_run_interrupted') },
    ],
  },
  {
    title: t('settings.webhook.group_business_title'),
    description: t('settings.webhook.group_business_desc'),
    items: [
      { value: 'TASK_INITIALIZED', label: t('settings.webhook.event_task_initialized') },
      { value: 'TASK_COMPLETED', label: t('settings.webhook.event_task_completed') },
      { value: 'TASK_FAILED', label: t('settings.webhook.event_task_failed') },
    ],
  },
])

watch(path, async current => {
  const revision = ++version
  config.value = defaults(); error.value = ''; message.value = ''; loading.value = true
  try {
    const { data } = await api.get(current)
    if (revision === version) config.value = data
  } catch (exc) {
    if (revision === version) error.value = formatApiError(exc, t('settings.webhook.load_failed'))
  } finally {
    if (revision === version) loading.value = false
  }
}, { immediate: true })

const selectLocation = (location: 'server' | 'desktop') => {
  if (busy.value) return
  if (location === 'desktop' && !hasDesktopNative.value) return
  config.value.delivery_location = location
}

const isGroupAllChecked = (group: (typeof groups.value)[number]) => {
  return group.items.every(item => config.value.events.includes(item.value))
}

const toggleGroupAll = (group: (typeof groups.value)[number]) => {
  if (busy.value) return
  const allChecked = isGroupAllChecked(group)
  const groupValues = group.items.map(i => i.value)
  if (allChecked) {
    config.value.events = config.value.events.filter(e => !groupValues.includes(e))
  } else {
    const set = new Set([...config.value.events, ...groupValues])
    config.value.events = Array.from(set)
  }
}

const act = async (test = false) => {
  if (busy.value || loading.value) return
  const revision = version, current = path.value
  busy.value = true; error.value = ''; message.value = ''
  try {
    if (!test) {
      await api.put(current, config.value)
      if (revision === version) message.value = t('settings.webhook.saved_success')
    } else {
      const { data } = await api.post(`${current}/test`, config.value)
      const result = data.request ? await window.sddDesktop?.webhooks?.send(data.request) : data
      if (revision !== version) return
      if (result?.ok) {
        message.value = t('settings.webhook.test_success')
      } else {
        error.value = `${t('settings.webhook.test_failed_prefix')}${result?.error || t('settings.webhook.test_failed_desktop_hint')}`
      }
    }
  } catch (exc) {
    if (revision === version) error.value = formatApiError(exc, t(test ? 'settings.webhook.test_failed' : 'settings.webhook.save_failed'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="webhook-settings">
    <!-- 头部区分：标题 + 右上角启用开关 -->
    <header class="section-header">
      <div class="header-titles">
        <div class="title-row">
          <h2>{{ scope === 'workspace' ? $t('settings.webhook.workspace_title') : $t('settings.webhook.personal_title') }}</h2>
          <span v-if="scope === 'workspace'" class="scope-tag workspace">{{ $t('settings.webhook.workspace_tag') }}</span>
          <span v-else class="scope-tag personal">{{ $t('settings.webhook.personal_tag') }}</span>
        </div>
      </div>

      <!-- 右上角开关：启用事件广播 -->
      <div class="header-actions">
        <label class="switch-toggle" :class="{ disabled: busy || loading }">
          <span class="switch-text">{{ $t('settings.webhook.enable_broadcast') }}</span>
          <input v-model="config.enabled" type="checkbox" :disabled="busy || loading" />
          <span class="switch-slider"></span>
        </label>
      </div>
    </header>

    <div v-if="loading" class="loading"><Loader2 class="w-4 h-4 spin" /> {{ $t('settings.webhook.loading') }}</div>

    <form v-else @submit.prevent="act()">
      <!-- 个人 Webhook 专有：场景卡片选择区 -->
      <div v-if="scope === 'personal'" class="scenes-section">
        <span class="scenes-label">{{ $t('settings.webhook.scene_label') }}</span>
        <div class="scene-cards">
          <!-- 卡片 1: 服务端出站投递（公网 Webhook） -->
          <div
            class="scene-card"
            :class="{ active: config.delivery_location === 'server', disabled: busy }"
            @click="selectLocation('server')"
          >
            <div class="scene-card-header">
              <span class="scene-badge recommend">{{ $t('settings.webhook.scene_server_badge') }}</span>
              <div class="scene-title">🌐 {{ $t('settings.webhook.scene_server_title') }}</div>
            </div>
            <p class="scene-desc">
              {{ $t('settings.webhook.scene_server_desc') }}
            </p>
          </div>

          <!-- 卡片 2: 本地回环代理（桌面客户端代发） -->
          <div
            class="scene-card"
            :class="{
              active: config.delivery_location === 'desktop',
              disabled: busy || !hasDesktopNative
            }"
            @click="selectLocation('desktop')"
          >
            <div class="scene-card-header">
              <span class="scene-badge dev">{{ hasDesktopNative ? $t('settings.webhook.scene_desktop_badge_dev') : $t('settings.webhook.scene_desktop_badge_need') }}</span>
              <div class="scene-title">💻 {{ $t('settings.webhook.scene_desktop_title') }}</div>
            </div>
            <p class="scene-desc">
              {{ $t('settings.webhook.scene_desktop_desc') }}
            </p>
          </div>
        </div>
      </div>

      <!-- 工作区 Webhook 专有：团队全员统一投递说明（黄色提示增强感） -->
      <div v-else class="workspace-banner">
        <div class="banner-title">
          <AlertTriangle class="w-4 h-4 text-amber-600 flex-shrink-0" />
          <span>{{ $t('settings.webhook.workspace_banner_title') }}</span>
        </div>
        <p class="banner-desc">{{ $t('settings.webhook.workspace_banner_desc') }}</p>
      </div>

      <!-- 端点 URL 输入框 -->
      <label class="field">
        <span class="field-label">{{ $t('settings.webhook.url_label') }}</span>
        <input
          v-model.trim="config.url"
          type="url"
          :placeholder="config.delivery_location === 'desktop' ? $t('settings.webhook.url_placeholder_desktop') : $t('settings.webhook.url_placeholder_server')"
          autocomplete="off"
          :disabled="busy"
        />
      </label>

      <!-- 事件订阅分组 -->
      <fieldset v-for="group in groups" :key="group.title" class="event-group" :disabled="busy">
        <div class="group-header">
          <div class="group-header-text">
            <legend class="group-title">{{ group.title }}</legend>
            <p class="group-desc">{{ group.description }}</p>
          </div>
          <div class="group-actions">
            <span class="group-count">
              {{ group.items.filter(i => config.events.includes(i.value)).length }}/{{ group.items.length }}
            </span>
            <button
              type="button"
              class="btn-batch-select"
              :disabled="busy"
              @click="toggleGroupAll(group)"
            >
              {{ isGroupAllChecked(group) ? $t('settings.webhook.clear_all') : $t('settings.webhook.select_all') }}
            </button>
          </div>
        </div>

        <div class="event-items-grid">
          <label
            v-for="item in group.items"
            :key="item.value"
            class="event-check-card"
            :class="{ active: config.events.includes(item.value), disabled: busy }"
          >
            <input
              v-model="config.events"
              type="checkbox"
              :value="item.value"
              :disabled="busy"
              class="custom-checkbox"
            />
            <span class="event-label">{{ item.label }}</span>
          </label>
        </div>
      </fieldset>

      <!-- 操作按钮栏：调换位置，挪到右下角，对齐系统统一按钮样式 -->
      <div class="actions">
        <div class="action-feedback">
          <p v-if="message" class="status-msg success" role="status">{{ message }}</p>
          <p v-if="error" class="status-msg error" role="alert">{{ error }}</p>
        </div>

        <div class="button-group">
          <!-- 发送测试消息在前（左） -->
          <button
            type="button"
            class="btn-secondary"
            :disabled="busy || !config.url"
            @click="act(true)"
          >
            <Send class="w-4 h-4" />
            <span>{{ $t('settings.webhook.send_test') }}</span>
          </button>

          <!-- 保存配置在后（右，主操作） -->
          <button
            type="submit"
            class="btn-primary"
            :disabled="busy"
          >
            <Loader2 v-if="busy" class="w-4 h-4 spin" />
            <Save v-else class="w-4 h-4" />
            <span>{{ $t('settings.webhook.save') }}</span>
          </button>
        </div>
      </div>
    </form>
  </section>
</template>

<style scoped>
.webhook-settings { padding: 28px; max-width: 820px; }
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
.header-titles { flex: 1; }
.header-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.title-row { display: flex; align-items: center; gap: 10px; margin-bottom: 0; }
h2 { margin: 0; font-size: 20px; font-weight: 700; color: #0f172a; }
.scope-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 9999px;
}
.scope-tag.personal { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
.scope-tag.workspace { background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }

/* 开关样式 */
.switch-toggle {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}
.switch-toggle.disabled {
  opacity: .55;
  cursor: not-allowed;
}
.switch-toggle input {
  display: none;
}
.switch-text {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}
.switch-slider {
  position: relative;
  width: 40px;
  height: 22px;
  border-radius: 999px;
  background: #cbd5e1;
  transition: background .2s ease;
  display: inline-block;
  flex-shrink: 0;
}
.switch-slider::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.2);
  transition: transform .2s ease;
}
.switch-toggle input:checked + .switch-slider {
  background: #0284c7;
}
.switch-toggle input:checked + .switch-slider::after {
  transform: translateX(18px);
}

/* 场景卡片 */
.scenes-section { margin: 18px 0; }
.scenes-label { display: block; font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 8px; }
.scene-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.scene-card {
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  padding: 14px;
  background: #fff;
  cursor: pointer;
  transition: all .2s ease;
  display: flex;
  flex-direction: column;
}
.scene-card:hover:not(.disabled) { border-color: #94a3b8; box-shadow: 0 2px 8px rgba(0, 0, 0, .04); }
.scene-card.active {
  border-color: #0284c7;
  border-width: 2px;
  padding: 13px;
  background: #f0f9ff;
}
.scene-card.disabled { opacity: .55; cursor: not-allowed; }
.scene-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.scene-title { font-size: 13px; font-weight: 600; color: #0f172a; }
.scene-badge { font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px; }
.scene-desc { font-size: 12px; color: #64748b; margin: 4px 0 0; line-height: 1.5; flex: 1; }

/* 工作区专属 Banner（黄色增强提示感，统一精致细边框） */
.workspace-banner {
  padding: 12px 16px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
  margin: 16px 0;
}
.banner-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #92400e;
}
.banner-desc {
  font-size: 12px;
  color: #b45309;
  margin: 6px 0 0;
  line-height: 1.6;
}

/* 端点输入框 */
.field { display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: #334155; margin: 18px 0 14px; }
.field-label { font-weight: 600; }
.field > input { width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; color: #0f172a; font-size: 13px; }
.field > input:focus { outline: none; border-color: #0284c7; ring: 2px solid #bae6fd; }

/* 事件订阅分组卡片与多选框现代化 */
.event-group {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  padding: 16px 18px;
  margin: 18px 0;
}
.group-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.group-header-text {
  flex: 1;
}
.group-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
  padding: 0;
}
.group-desc {
  font-size: 12px;
  color: #64748b;
  margin: 4px 0 0;
  line-height: 1.5;
}
.group-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.group-count {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 7px;
  border-radius: 6px;
}
.btn-batch-select {
  font-size: 12px;
  font-weight: 500;
  color: #0284c7;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  padding: 3px 9px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-batch-select:hover:not(:disabled) {
  background: #e0f2fe;
  border-color: #7dd3fc;
  color: #0369a1;
}
.btn-batch-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.event-items-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.event-check-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s ease;
}
.event-check-card:hover:not(.disabled) {
  border-color: #cbd5e1;
  background: #f8fafc;
}
.event-check-card.active {
  border-color: #bae6fd;
  background: #f0f9ff;
}
.event-check-card.disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.event-label {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
  transition: color 0.15s ease;
}
.event-check-card.active .event-label {
  color: #0369a1;
  font-weight: 600;
}

/* 统一高级复选框样式（对齐项目设计系统） */
.custom-checkbox {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  margin: 0;
  border-radius: 5px;
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
.custom-checkbox:hover:not(:checked):not(:disabled) {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}
.custom-checkbox:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.25);
}
.custom-checkbox:checked:hover:not(:disabled) {
  border-color: #0284c7;
  background-color: #0284c7;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.35);
}
.custom-checkbox:focus-visible {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.22);
}
.custom-checkbox:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  background-color: #f8fafc;
  border-color: #e2e8f0;
}

/* 底部操作区：对齐右下角 */
.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  margin-top: 28px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}
.action-feedback {
  margin-right: auto;
}
.button-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.status-msg {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
}
.status-msg.success { color: #15803d; }
.status-msg.error { color: #be123c; }

/* 按钮样式对齐系统设计系统 */
.btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  border-radius: 0.75rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #334155;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
}
.btn-secondary:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}
.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  border-radius: 0.75rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #ffffff;
  background-color: var(--color-primary-500, #0ea5e9);
  border: 1px solid transparent;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.25);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) {
  background-color: var(--color-primary-600, #0284c7);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(14, 165, 233, 0.35);
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.loading { display: flex; align-items: center; gap: 12px; margin-top: 20px; font-size: 13px; color: #64748b; }
.spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 720px) {
  .webhook-settings { padding: 18px; }
  .section-header { flex-direction: column; align-items: flex-start; gap: 12px; }
  .scene-cards { grid-template-columns: 1fr; }
  .event-items-grid { grid-template-columns: 1fr; }
  .actions { flex-direction: column; align-items: stretch; gap: 12px; }
  .button-group { width: 100%; justify-content: flex-end; }
}
</style>
