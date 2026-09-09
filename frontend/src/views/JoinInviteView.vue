<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, CheckCircle2, LogIn } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

type InvitePreview = {
  token: string
  workspace_id: string
  workspace_name: string
  role: string
  is_expert: boolean
  expires_at: string | null
  status: string
  created_by_name: string
}

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const token = computed(() => String(route.params.token || ''))

const loading = ref(true)
const loadError = ref('')
const preview = ref<InvitePreview | null>(null)
const accepting = ref(false)
const acceptError = ref('')
const acceptResult = ref<{ workspace_id: string; already_member: boolean } | null>(null)

const isAuthenticated = computed(() => authStore.isAuthenticated)

const roleText = (role: string) => {
  if (role === 'OWNER') return t('settings.members.role_owner')
  if (role === 'DEVELOPER') return t('settings.members.role_developer')
  return t('settings.members.role_viewer')
}

const statusText = (status: string) => t(`invite.status_${status.toLowerCase()}`)

const expireText = computed(() => {
  if (!preview.value?.expires_at) return t('invite.no_expiry')
  return t('invite.expire_at', { date: new Date(preview.value.expires_at).toLocaleDateString() })
})

const loadPreview = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.get(`/invites/${token.value}`)
    preview.value = res.data
  } catch (error) {
    if ((error as { response?: { status?: number } })?.response?.status === 404) {
      loadError.value = t('invite.invalid_link')
    } else {
      loadError.value = formatApiError(error, t('invite.load_failed'), t)
    }
  } finally {
    loading.value = false
  }
}

const acceptInvite = async () => {
  if (!preview.value || accepting.value) return
  if (!authStore.isAuthenticated) {
    router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }

  accepting.value = true
  acceptError.value = ''
  try {
    const res = await api.post(`/invites/${token.value}/accept`)
    acceptResult.value = res.data
  } catch (error) {
    acceptError.value = formatApiError(error, t('invite.accept_failed'), t)
  } finally {
    accepting.value = false
  }
}

const goWorkspace = () => {
  if (!acceptResult.value) return
  router.push(`/ws/${acceptResult.value.workspace_id}/dashboard`)
}

onMounted(async () => {
  if (!authStore.user && authStore.isAuthenticated) {
    await authStore.fetchCurrentUser()
  }
  await loadPreview()
})
</script>

<template>
  <div class="join-page">
    <div class="join-card">
      <div class="join-brand">TraceForge</div>

      <div v-if="loading" class="join-loading">
        <span class="join-spinner"></span>
        <span>{{ $t('invite.loading') }}</span>
      </div>

      <div v-else-if="loadError" class="join-state">
        <AlertTriangle class="w-6 h-6 join-state-icon warn" />
        <p>{{ loadError }}</p>
      </div>

      <template v-else-if="preview">
        <template v-if="!acceptResult">
          <h1>{{ $t('invite.title') }}</h1>
          <p class="join-workspace">{{ preview.workspace_name }}</p>

          <div class="join-meta">
            <div class="join-meta-row">
              <span>{{ $t('invite.join_role') }}</span>
              <b>{{ roleText(preview.role) }}</b>
            </div>
            <div class="join-meta-row">
              <span>{{ $t('invite.join_expiry') }}</span>
              <b>{{ expireText }}</b>
            </div>
            <div v-if="preview.created_by_name" class="join-meta-row">
              <span>{{ $t('invite.invited_by') }}</span>
              <b>{{ preview.created_by_name }}</b>
            </div>
          </div>

          <div v-if="preview.status !== 'ACTIVE'" class="join-state">
            <AlertTriangle class="w-6 h-6 join-state-icon warn" />
            <p>{{ statusText(preview.status) }}</p>
          </div>

          <div v-if="acceptError" class="join-error">{{ acceptError }}</div>

          <button
            v-if="preview.status === 'ACTIVE' && isAuthenticated"
            class="join-btn primary"
            :disabled="accepting"
            @click="acceptInvite"
          >
            <span v-if="accepting" class="join-spinner dark"></span>
            {{ accepting ? $t('invite.accepting') : $t('invite.accept') }}
          </button>
          <button
            v-else-if="preview.status === 'ACTIVE' && !isAuthenticated"
            class="join-btn primary"
            @click="acceptInvite"
          >
            <LogIn class="w-4 h-4" />
            {{ $t('invite.login_and_accept') }}
          </button>
        </template>

        <template v-else>
          <div class="join-state ok-state">
            <CheckCircle2 class="w-7 h-7 join-state-icon ok" />
            <p>{{ acceptResult.already_member ? $t('invite.already_member') : $t('invite.success') }}</p>
          </div>
          <button class="join-btn primary" @click="goWorkspace">
            {{ $t('invite.go_workspace') }}
          </button>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.join-page {
  min-height: 100vh;
  background: linear-gradient(180deg, #f0f9ff 0%, #f8fafc 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  font-family: 'Plus Jakarta Sans', 'Microsoft YaHei', -apple-system, sans-serif;
}

.join-card {
  width: 100%;
  max-width: 420px;
  background: #ffffff;
  border: 1px solid #dbe8f6;
  border-top: 4px solid #0ea5e9;
  border-radius: 18px;
  box-shadow: 0 30px 60px -24px rgba(2, 132, 199, 0.35);
  padding: 2rem 1.75rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}

.join-brand {
  font-size: 0.82rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #94a3b8;
  text-transform: uppercase;
}

.join-loading {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  color: #64748b;
  font-size: 0.9rem;
  padding: 2rem 0;
}

.join-card h1 {
  margin: 0;
  font-size: 1.25rem;
  color: #0f172a;
  font-weight: 800;
}

.join-name {
  margin: 0;
  font-size: 1.02rem;
  color: #0369a1;
  font-weight: 700;
}

.join-meta {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fbff;
  padding: 0.4rem 0.9rem;
}

.join-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.5rem 0;
  font-size: 0.84rem;
  border-bottom: 1px dashed #e2e8f0;
}

.join-meta-row:last-child {
  border-bottom: none;
}

.join-meta-row span {
  color: #64748b;
}

.join-meta-row b {
  color: #0f172a;
}

.join-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0;
}

.join-state p {
  margin: 0;
  font-size: 0.9rem;
  color: #334155;
}

.join-state-icon.warn {
  color: #d97706;
}

.join-state-icon.ok {
  color: #16a34a;
}

.join-btn {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.7rem 1rem;
  border-radius: 12px;
  font-size: 0.9rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
  font-family: inherit;
}

.join-btn.primary {
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  color: #ffffff;
  box-shadow: 0 8px 18px -6px rgba(37, 99, 235, 0.5);
}

.join-btn.primary:hover:not(:disabled) {
  filter: brightness(1.05);
  transform: translateY(-1px);
}

.join-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.join-error {
  width: 100%;
  background: #fff1f2;
  border: 1px solid #fecaca;
  color: #be123c;
  border-radius: 10px;
  padding: 0.6rem 0.75rem;
  font-size: 0.8rem;
}

.join-spinner {
  width: 1rem;
  height: 1rem;
  border-radius: 50%;
  border: 2px solid rgba(14, 165, 233, 0.25);
  border-top-color: #0ea5e9;
  animation: joinSpin 0.8s linear infinite;
}

.join-spinner.dark {
  border-color: rgba(255, 255, 255, 0.35);
  border-top-color: #ffffff;
}

@keyframes joinSpin {
  to { transform: rotate(360deg); }
}
</style>
