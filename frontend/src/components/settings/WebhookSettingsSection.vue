<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import api from '@/utils/api'
import BaseSelect from '@/components/BaseSelect.vue'
import { Loader2, Send, Save } from '@/components/icons'
import { formatApiError } from '@/utils/error'

const props = defineProps<{ scope: 'personal' | 'workspace'; workspaceId?: string }>()
type Config = { enabled: boolean; url: string; delivery_location: string; events: string[] }
const defaults = (): Config => ({ enabled: false, url: '', delivery_location: 'server', events: ['AI_HITL_SUSPENDED', 'AI_RUN_FINISHED', 'AI_RUN_ERROR'] })
const config = ref(defaults())
const busy = ref(false)
const loading = ref(false)
const message = ref('')
const error = ref('')
let version = 0
const path = computed(() => props.scope === 'workspace' ? `/workspaces/${props.workspaceId}/task-webhook` : '/users/me/task-webhook')
const locationOptions = [ { value: 'server', label: '服务端投递' }, { value: 'desktop', label: '当前桌面客户端投递', disabled: !window.sddDesktop?.webhooks } ]
const groups = [
  { title: 'AI 自动化执行态', description: 'AI 本轮运行的卡点、就绪、异常或人工中断，执行满 10 秒后广播。', items: [
    { value: 'AI_HITL_SUSPENDED', label: 'AI 遇到卡点等待确认' }, { value: 'AI_RUN_FINISHED', label: 'AI 长时间执行完毕就绪' }, { value: 'AI_RUN_ERROR', label: 'AI 执行异常报错' },
    { value: 'AI_RUN_INTERRUPTED', label: 'AI 本轮执行被人工中断' },
  ] },
  { title: '业务任务生命周期态', description: '人工操作成功后广播，不受 AI 执行时长限制。', items: [
    { value: 'TASK_INITIALIZED', label: '任务被人工初始化' },
    { value: 'TASK_COMPLETED', label: '任务被人工手动标记完成' },
    { value: 'TASK_FAILED', label: '任务被人工手动标记失败' },
  ] },
]
watch(path, async current => {
  const revision = ++version
  config.value = defaults(); error.value = ''; message.value = ''; loading.value = true
  try { const { data } = await api.get(current); if (revision === version) config.value = data }
  catch (exc) { if (revision === version) error.value = formatApiError(exc, '加载 Webhook 配置失败') }
  finally { if (revision === version) loading.value = false }
}, { immediate: true })
const act = async (test = false) => {
  if (busy.value || loading.value) return
  const revision = version, current = path.value
  busy.value = true; error.value = ''; message.value = ''
  try {
    if (!test) { await api.put(current, config.value); if (revision === version) message.value = 'Webhook 配置已保存' }
    else {
      const { data } = await api.post(`${current}/test`, config.value)
      const result = data.request ? await window.sddDesktop?.webhooks?.send(data.request) : data
      if (revision !== version) return
      if (result?.ok) message.value = '测试消息已送达'
      else error.value = `测试未送达：${result?.error || '请使用桌面客户端投递'}`
    }
  } catch (exc) { if (revision === version) error.value = formatApiError(exc, test ? '发送测试失败' : '保存失败') }
  finally { busy.value = false }
}
</script>

<template>
  <section class="webhook-settings">
    <header><h2>{{ scope === 'workspace' ? '工作区 Webhook' : '个人 Webhook' }}</h2><p>{{ scope === 'workspace' ? '广播工作区成员的 AI 长任务执行事件与人工任务操作，并附带发起人。' : '广播当前账号的 AI 长任务执行事件与人工任务操作，可投递到手机通知或本地外设。' }}</p></header>
    <p class="scope-note">站外广播不受页面或窗口焦点影响。纯浏览不广播；AI 执行事件满 10 秒后广播。</p>
    <div v-if="loading" class="loading"><Loader2 class="w-4 h-4 spin" /> 加载配置…</div>
    <form v-else @submit.prevent="act()">
      <label class="check-row enable"><input v-model="config.enabled" type="checkbox" :disabled="busy" /> 启用事件广播</label>
      <label class="field">端点 URL<input v-model.trim="config.url" type="url" placeholder="https://… 或 http://127.0.0.1:端口/…" autocomplete="off" :disabled="busy" /></label>
      <div class="fields">
        <label v-if="scope === 'personal'" class="field">投递位置<BaseSelect v-model="config.delivery_location" :options="locationOptions" :disabled="busy" /></label>
      </div>
      <p class="delivery-note">发送标准 JSON Webhook；接收端返回 HTTP 2xx 即确认送达。</p>
      <p class="delivery-note">{{ config.delivery_location === 'desktop' ? '本地地址指用户电脑；客户端在线时异步投递，离线后重连补送。' : '本地地址指服务端主机。要通知用户电脑上的监听器，请在个人设置选择桌面客户端投递。' }}</p>
      <fieldset v-for="group in groups" :key="group.title" :disabled="busy"><legend>{{ group.title }}</legend><p>{{ group.description }}</p><label v-for="item in group.items" :key="item.value" class="check-row"><input v-model="config.events" type="checkbox" :value="item.value" />{{ item.label }}</label></fieldset>
      <div class="actions"><button type="submit" class="primary" :disabled="busy"><Save class="w-4 h-4" />保存配置</button><button type="button" :disabled="busy || !config.url" @click="act(true)"><Send class="w-4 h-4" />发送测试消息</button><Loader2 v-if="busy" class="w-4 h-4 spin" /></div>
    </form>
    <p v-if="message" class="success" role="status">{{ message }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.webhook-settings { padding: 28px; max-width: 800px; }
h2 { margin: 0 0 8px; font-size: 20px; color: #0f172a; }
p { font-size: 13px; color: #64748b; line-height: 1.6; }
.scope-note { padding: 10px 12px; background: #f0f9ff; color: #0369a1; border-radius: 8px; }
.field { display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: #334155; margin: 18px 0; flex: 1; }
.field > input { width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; color: #0f172a; }
.fields { display: flex; gap: 16px; }
.delivery-note { margin-top: -4px; font-size: 12px; }
fieldset { border: 1px solid #e2e8f0; border-radius: 10px; margin: 20px 0; padding: 12px 16px 16px; }
legend { font-size: 14px; font-weight: 600; color: #334155; padding: 0 6px; }
fieldset p { margin: 0 0 12px; }
.check-row { display: flex; align-items: center; gap: 9px; font-size: 13px; color: #334155; padding: 7px 0; cursor: pointer; }
.check-row input { accent-color: #0284c7; }
.enable { font-weight: 600; }
.actions, .loading { display: flex; align-items: center; gap: 12px; }
.actions button { display: inline-flex; align-items: center; gap: 8px; padding: 9px 14px; border-radius: 8px; border: 1px solid #cbd5e1; background: #fff; color: #334155; cursor: pointer; }
.actions .primary { color: #fff; background: #0284c7; border-color: #0284c7; }
.actions button:disabled { opacity: .5; cursor: default; }
.success { color: #15803d; } .error { color: #be123c; }
.spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) { .fields { flex-direction: column; gap: 0; } .webhook-settings { padding: 18px; } }
</style>
