import { createApp } from 'vue'
import { createPinia } from 'pinia'
import i18n from '@/i18n'
import '@/assets/main.css'
import api, { buildApiBaseUrl, DEFAULT_SERVER_URL } from '@/utils/api'
import { TASK_FLOAT_ROUTE } from '@/types/taskFloat'
import TaskFloatWindow from '@/components/floating/TaskFloatWindow.vue'

const params = new URLSearchParams(location.hash.slice(`#${TASK_FLOAT_ROUTE}?`.length))
const id = params.get('id')
const workspaceId = params.get('workspaceId')
const taskId = params.get('taskId')
if (!id || !workspaceId || !taskId || !window.sddTaskFloat) {
  throw new Error('Missing task float context')
}

api.defaults.baseURL = buildApiBaseUrl(localStorage.getItem('sdd_server_url') || DEFAULT_SERVER_URL)
createApp(TaskFloatWindow, { id, workspaceId, taskId, controls: window.sddTaskFloat })
  .use(createPinia())
  .use(i18n)
  .mount('#app')
