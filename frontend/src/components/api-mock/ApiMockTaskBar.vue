<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Settings2, RefreshCw, Clock, Globe, FileUp } from 'lucide-vue-next'
import CollabPresenceBar from '@/components/api-mock/CollabPresenceBar.vue'

type JobState = {
  id: string
  job_type: string
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
  progress: number
  message?: string | null
  result_json?: Record<string, unknown> | null
}

type OnlinePresenceUser = {
  id: string
  displayName: string
  email?: string | null
  avatarSvg?: string | null
  avatarUrl?: string | null
}

type ConfigMode = 'sync' | 'versions' | 'proxy' | 'import'

const props = defineProps<{
  selectedTaskName: string
  currentSourceLabel: string
  canView: boolean
  activeJob: JobState | null
  swaggerMutationLocked: boolean
  collabConnected: boolean
  onlineUsers: OnlinePresenceUser[]
}>()

const emit = defineEmits<{
  (e: 'open-config', mode: ConfigMode): void
}>()

const { t } = useI18n()

const menuOpen = ref(false)

const selectConfigMode = (mode: ConfigMode) => {
  menuOpen.value = false
  emit('open-config', mode)
}

const jobTone = computed(() => {
  if (!props.activeJob) return 'idle'
  if (props.activeJob.status === 'FAILED') return 'failed'
  if (props.activeJob.status === 'SUCCESS') return 'success'
  return 'running'
})

const jobLabel = computed(() => {
  if (!props.activeJob) return ''
  const message = String(props.activeJob.message || '').trim()
  if (message) return message
  if (props.activeJob.status === 'PENDING') return t('api_mock.job_status_pending')
  if (props.activeJob.status === 'RUNNING') return t('api_mock.job_status_running')
  if (props.activeJob.status === 'SUCCESS') return t('api_mock.job_status_success')
  if (props.activeJob.status === 'FAILED') return t('api_mock.job_status_failed')
  return `${props.activeJob.job_type} ${props.activeJob.progress}%`
})
</script>

<template>
  <header class="task-bar glass-panel">
    <div class="task-bar-main">
      <div class="task-bar-copy">
        <span class="task-bar-kicker">API MOCK</span>
        <h1>{{ $t('api_mock.title') }}</h1>
        <p>{{ $t('api_mock.subtitle') }}</p>
      </div>

      <div class="task-bar-tools">
        <div class="config-menu-anchor">
          <button type="button" class="btn-secondary config-btn" :disabled="!canView" @click="menuOpen = !menuOpen">
            <Settings2 class="w-4 h-4" />
            {{ $t('api_mock.config_button') }}
          </button>

          <Transition name="fade-pop">
            <div v-if="menuOpen" class="config-popover">
              <button type="button" class="config-option" @click="selectConfigMode('sync')">
                <RefreshCw class="w-4 h-4" />
                <span>{{ $t('api_mock.config_menu_sync') }}</span>
              </button>
              <button type="button" class="config-option" @click="selectConfigMode('versions')">
                <Clock class="w-4 h-4" />
                <span>{{ $t('api_mock.config_menu_versions') }}</span>
              </button>
              <button type="button" class="config-option" @click="selectConfigMode('proxy')">
                <Globe class="w-4 h-4" />
                <span>{{ $t('api_mock.config_menu_proxy') }}</span>
              </button>
              <button type="button" class="config-option" @click="selectConfigMode('import')">
                <FileUp class="w-4 h-4" />
                <span>{{ $t('api_mock.config_menu_import') }}</span>
              </button>
            </div>
          </Transition>
        </div>
      </div>
    </div>

    <div class="task-bar-meta">
      <div class="meta-strip">
        <span class="meta-label">{{ $t('api_mock.task_ready') }}</span>
        <strong>{{ selectedTaskName }}</strong>
      </div>
      <div class="meta-strip">
        <span class="meta-label">{{ $t('api_mock.current_source_label') }}</span>
        <strong>{{ currentSourceLabel }}</strong>
      </div>
      <div v-if="activeJob" class="meta-strip job-strip" :class="`tone-${jobTone}`">
        <span class="meta-label">{{ $t('api_mock.sync_status') }}</span>
        <strong>{{ jobLabel }}</strong>
        <span class="job-progress">{{ activeJob.progress }}%</span>
      </div>
      <div v-if="swaggerMutationLocked" class="meta-strip lock-strip">
        <span class="meta-label">{{ $t('api_mock.sync_status') }}</span>
        <strong>{{ $t('api_mock.ai_auto_mock_running') }}</strong>
      </div>
      <CollabPresenceBar :connected="collabConnected" :users="onlineUsers" />
    </div>
  </header>
</template>

<style scoped>
.task-bar {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.2rem 1.3rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.03);
  position: relative;
  z-index: 40;
}

.task-bar-main {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}

.task-bar-copy {
  min-width: 0;
}

.task-bar-kicker {
  display: inline-flex;
  align-items: center;
  padding: 0.28rem 0.72rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.task-bar-copy h1 {
  margin: 0.65rem 0 0.35rem;
  font-size: 1.8rem;
  color: #0f172a;
}

.task-bar-copy p {
  margin: 0;
  max-width: 42rem;
  color: #64748b;
  line-height: 1.65;
}

.task-bar-tools {
  display: flex;
  justify-content: flex-end;
  width: min(16rem, 100%);
}

.meta-label {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #0369a1;
  text-transform: uppercase;
}

.config-btn {
  min-width: 11.5rem;
  min-height: 3rem;
  border-radius: 18px;
  font-weight: 700;
}

.config-menu-anchor {
  position: relative;
}

.config-popover {
  position: absolute;
  top: calc(100% + 0.4rem);
  right: 0;
  z-index: 100;
  min-width: 13rem;
  padding: 0.35rem;
  border-radius: 16px;
  border: 1px solid #dbeafe;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(12px);
}

.config-option {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: #334155;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
  transition: background 0.12s ease;
}

.config-option:hover {
  background: #eff6ff;
  color: #0369a1;
}

.fade-pop-enter-active,
.fade-pop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.fade-pop-enter-from,
.fade-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}

.task-bar-meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 0.75rem;
  align-items: stretch;
}

.meta-strip {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  justify-content: center;
  min-height: 4.1rem;
  padding: 0.78rem 0.92rem;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid #e2e8f0;
}

.lock-strip {
  border: 1px solid rgba(251, 146, 60, 0.35);
  background: rgba(255, 247, 237, 0.9);
}

.lock-strip strong {
  color: #9a3412;
}

.meta-strip strong {
  color: #0f172a;
  font-size: 0.95rem;
}

.job-strip {
  position: relative;
  padding-right: 4rem;
}

.job-progress {
  position: absolute;
  top: 0.85rem;
  right: 0.95rem;
  min-width: 2.7rem;
  text-align: center;
  padding: 0.2rem 0.48rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
  background: #f8fafc;
  color: #0369a1;
}

.tone-running {
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.28);
}

.tone-success {
  background: rgba(240, 253, 244, 0.92);
  border-color: rgba(134, 239, 172, 0.9);
}

.tone-success .job-progress {
  background: rgba(220, 252, 231, 0.96);
  color: #15803d;
}

.tone-failed {
  background: rgba(254, 242, 242, 0.96);
  border-color: rgba(252, 165, 165, 0.9);
}

.tone-failed .job-progress {
  background: rgba(254, 226, 226, 0.98);
  color: #b91c1c;
}

@media (max-width: 1280px) {
  .task-bar-main {
    flex-direction: column;
  }

  .task-bar-tools {
    width: 100%;
  }

  .task-bar-meta {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .task-bar-tools {
    grid-template-columns: 1fr;
  }

  .config-btn {
    min-height: 3.2rem;
  }
}
</style>
