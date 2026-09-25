<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Server,
  Network,
  FolderGit2,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Info,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Folder,
  Play,
  Loader2,
  Check,
  RefreshCw,
} from 'lucide-vue-next'
import api from '@/utils/api'
import BaseSelect from '@/components/BaseSelect.vue'
import LocalGitRemoteSelect from '@/components/local-agent/LocalGitRemoteSelect.vue'
import { getSddDesktop } from '@/utils/runtime'
import { useLocalServiceConnectionsStore } from '@/stores/localServiceConnections'
import { useAuthStore } from '@/stores/auth'
import { useLocalAgentStore } from '@/stores/localAgent'
import { useServiceRepositoryMappings } from '@/composables/useServiceRepositoryMappings'
import { formatApiError } from '@/utils/error'
import { useLocalResources, type ResourceDraft } from '@/composables/useLocalResources'

const props = defineProps<{ workspaceId: string }>()
const emit = defineEmits<{ saved: [] }>()

const { items, enabled, busy, error, load, save } = useLocalResources(() => props.workspaceId)
const auth = useAuthStore()
const localAgent = useLocalAgentStore()
const desktop = computed(() => getSddDesktop())
const repoMappings = useServiceRepositoryMappings(() => props.workspaceId, () => String(auth.user?.id || ''))
const { independent: independentRepos } = repoMappings
const syncingRepo = ref('')
async function synchronizeRepo(mapping: ResourceDraft['repositories'][number]) {
  syncingRepo.value = mapping.repository_id
  error.value = ''
  try { await repoMappings.synchronize(mapping) }
  catch (e) { error.value = formatApiError(e, '同步本地仓库映射失败') }
  finally { syncingRepo.value = '' }
}

const starting = ref(false)
const serviceStarted = ref(false)
const selected = ref('')
const engine = ref('')
const currentStep = ref(0)
const showHostToken = ref(false)
const showAgentToken = ref(false)
const connectionStatus = ref<'idle' | 'checking' | 'failed'>('idle')
const saveFeedback = ref('')
const connections = useLocalServiceConnectionsStore()
const connectionKey = computed(() => JSON.stringify([
  api.defaults?.baseURL || '', auth.user?.id || '', props.workspaceId, selected.value, form.backend,
]))
const connectionChecked = computed(() => connections.matches(connectionKey.value, connectionDraft.value))
const connectionDraft = computed(() => ({
  resource_id: selected.value || undefined,
  backend: form.backend,
  service_url: form.service_url,
  resource_service_url: form.resource_service_url,
  host_token: form.host_token || undefined,
  agent_token: form.agent_token || undefined,
  agent_username: form.agent_username,
}))

const profileOptions = computed(() => [
  { label: '+ 新建配置方案', value: '' },
  ...items.value.map((item) => ({ label: item.name, value: item.id })),
])

function profileSelectionKey() {
  return `local-service-selected-profile:${String(auth.user?.id || '')}:${props.workspaceId}`
}

function rememberSelectedProfile(id: string) {
  if (!id) return
  try { localStorage.setItem(profileSelectionKey(), id) } catch { /* The profile list still provides a fallback. */ }
}

function initialProfileId() {
  try {
    const remembered = localStorage.getItem(profileSelectionKey())
    if (remembered && items.value.some((item) => item.id === remembered)) return remembered
  } catch { /* Use the newest saved profile when local storage is unavailable. */ }
  return items.value[0]?.id || ''
}

function handleProfileChange(val: string) {
  selected.value = val
  rememberSelectedProfile(val)
  edit()
}

const form = reactive<ResourceDraft>({
  name: '我的本地服务',
  backend: 'opencode',
  service_url: '',
  resource_service_url: '',
  workspace_root: '',
  repositories: [],
  host_token: '',
  agent_token: '',
  agent_username: 'opencode',
})

const supported = computed(() => ['opencode', 'dsh'].includes(engine.value))
watch([connectionDraft, connectionKey], () => { connectionStatus.value = 'idle' }, { flush: 'sync' })
watch(form, () => { saveFeedback.value = '' }, { deep: true, flush: 'sync' })

watch(
  () => props.workspaceId,
  async () => {
    selected.value = ''
    serviceStarted.value = false
    currentStep.value = 0
    await load()
    try {
      const [workspace, backend] = await Promise.all([
        api.get(`/workspaces/${props.workspaceId}`),
        api.get(`/workspaces/${props.workspaceId}/agent-backends`),
      ])
      engine.value = backend.data.effective_agent_backend
      if (supported.value) form.backend = engine.value as 'opencode' | 'dsh'
      await localAgent.loadLocalConfig()
      await localAgent.setWorkspaceContext(workspace.data)
      form.repositories = repoMappings.initialize(workspace.data.repositories || [])
      selected.value = initialProfileId()
      if (selected.value) rememberSelectedProfile(selected.value)
      edit()
    } catch {
      error.value = '读取工作区配置失败'
    }
  },
  { immediate: true },
)

function edit() {
  saveFeedback.value = ''
  currentStep.value = 0
  serviceStarted.value = false
  const item = items.value.find((r) => r.id === selected.value)
  if (!item) {
    Object.assign(form, {
      name: '我的本地服务',
      backend: supported.value ? (engine.value as 'opencode' | 'dsh') : 'opencode',
      service_url: '',
      resource_service_url: '',
      workspace_root: '',
      repositories: repoMappings.defaults(),
      host_token: '',
      agent_token: '',
      agent_username: 'opencode',
    })
    Object.assign(form, connections.checked[connectionKey.value] || {})
    return
  }
  Object.assign(form, {
    name: item.name,
    backend: item.backend,
    service_url: item.service_url,
    resource_service_url: item.resource_service_url,
    workspace_root: item.workspace_root,
    repositories: item.repositories_json.map((r) => ({ ...r })),
    host_token: '',
    agent_token: '',
  })
  Object.assign(form, connections.checked[connectionKey.value] || {})
  repoMappings.restore(form.repositories)
}

async function persist() {
  if (currentStep.value !== 2 || busy.value || starting.value || !connectionChecked.value) return
  saveFeedback.value = ''

  const defaultName = form.name?.trim() || (selected.value ? '' : '我的本地服务')
  let profileName = ''
  try {
    const promptRes = await ElMessageBox.prompt('请为当前本地服务配置方案命名：', '保存配置方案', {
      confirmButtonText: '保存配置',
      cancelButtonText: '取消',
      inputValue: defaultName,
      inputPlaceholder: '例如：我的主力工作站 (RTX 4090)',
      inputValidator: (val) => {
        if (!val || !val.trim()) return '配置方案名称不能为空'
        if (val.trim().length > 100) return '配置方案名称不能超过 100 个字符'
        return true
      },
    })
    profileName = (promptRes.value || '').trim()
  } catch {
    return
  }

  form.name = profileName

  for (const mapping of form.repositories) {
    if (!independentRepos.value[mapping.repository_id]) repoMappings.reuse(mapping)
  }
  try {
    await desktop.value?.resources?.configureRoots?.({
      backend: form.backend,
      resourceServiceUrl: form.resource_service_url,
      workspaceRoot: form.workspace_root,
      repoRoots: form.repositories.map((r) => r.local_path).filter(Boolean),
    })
  } catch (e) {
    error.value = formatApiError(e, '配置本地目录失败')
    return
  }
  const draft = {
    ...form,
    name: profileName,
    host_token: form.host_token || undefined,
    agent_token: form.agent_token || undefined,
  }
  const result = await save(draft, selected.value || undefined)
  if (result) {
    serviceStarted.value = false
    selected.value = result.id
    rememberSelectedProfile(result.id)
    form.host_token = ''
    form.agent_token = ''
    connections.save(connectionKey.value, connectionDraft.value)
    saveFeedback.value = '本地服务配置已保存'
    ElMessage.success(saveFeedback.value)
    emit('saved')
  }
}

async function startLocal() {
  const desk = desktop.value
  if (!desk?.resources || starting.value || busy.value || currentStep.value !== 0) return
  const key = connectionKey.value

  starting.value = true
  serviceStarted.value = false
  error.value = ''
  try {
    const result = await desk.resources.start({
      backend: form.backend,
    })
    if (key !== connectionKey.value) return
    Object.assign(form, result)
    serviceStarted.value = true
    await check()
  } catch (e) {
    error.value = formatApiError(e, '启动本地服务失败')
  } finally {
    starting.value = false
  }
}

async function check() {
  if (busy.value) return
  const draft = connectionDraft.value
  const workspaceId = props.workspaceId
  const key = connectionKey.value
  busy.value = true
  error.value = ''
  connections.invalidate(key)
  connectionStatus.value = 'checking'
  try {
    const { data } = await api.post(`/workspaces/${workspaceId}/local-resources/check-connection`, draft)
    if (data?.ready !== true) throw new Error('服务连接检测未通过')
    if (draft === connectionDraft.value && key === connectionKey.value) {
      connections.save(key, draft)
      connectionStatus.value = 'idle'
    }
  } catch (e) {
    if (draft === connectionDraft.value && key === connectionKey.value) {
      connectionStatus.value = 'failed'
      error.value = formatApiError(e, '服务连接检测失败')
    }
  } finally {
    busy.value = false
  }
}

async function selectWorkspaceRoot() {
  const desk = desktop.value
  if (!desk?.git?.selectDirectory) return
  const result = await desk.git.selectDirectory()
  if (!result.canceled && result.path) {
    form.workspace_root = result.path
  }
}

async function selectRepoPath(mapping: ResourceDraft['repositories'][number]) {
  const desk = desktop.value
  if (!desk?.git?.selectDirectory) return
  const result = await desk.git.selectDirectory()
  if (!result.canceled && result.path) {
    repoMappings.setLocalPath(mapping, result.path)
  }
}

const steps = [
  { id: 0, title: '服务地址与网络', desc: '服务端点与访问凭据', icon: Network },
  { id: 1, title: '工作区目录', desc: '任务 worktree 存放位置', icon: Folder },
  { id: 2, title: '代码仓库映射', desc: '复用映射或指定独立目录', icon: FolderGit2 },
]
</script>

<template>
  <section class="local-service-section glass-panel">
    <!-- Header: Title, Profile Switcher & Desktop Quick Actions -->
    <header class="section-header">
      <div class="header-left">
        <div class="icon-wrapper">
          <Server class="w-6 h-6 text-sky-500" />
        </div>
        <div>
          <div class="title-row">
            <h2 class="title-gradient-small">本地服务地址设置</h2>
            <span v-if="connectionStatus === 'checking'" class="status-badge status-idle" role="status">
              <Loader2 class="w-3.5 h-3.5 spin" />
              连接检测中
            </span>
            <span v-else-if="connectionStatus === 'failed'" class="status-badge status-error" role="status">
              <AlertCircle class="w-3.5 h-3.5" />
              连接检测失败
            </span>
            <span v-else-if="connectionChecked" class="status-badge status-ready" role="status">
              <CheckCircle2 class="w-3.5 h-3.5" />
              连接检测通过
            </span>
            <span v-else class="status-badge status-idle">
              <Info class="w-3.5 h-3.5" />
              待检测连接
            </span>
          </div>
          <p class="subtitle">
            配置当前账号专属的本地 Agent 与同机资源计算节点。支持 Web 与 Electron 跨端任务调用。
          </p>
        </div>
      </div>

      <!-- Top Right Controls -->
      <div class="header-controls">
        <div class="profile-select-wrapper">
          <BaseSelect
            v-model="selected"
            :options="profileOptions"
            size="sm"
            @update:model-value="handleProfileChange"
          />
          <span v-if="selected" class="profile-current-badge" title="当前正在查看和编辑的已保存方案">
            <CheckCircle2 class="w-3.5 h-3.5" />
            当前方案
          </span>
        </div>
      </div>
    </header>

    <!-- Guard States: Not Enabled or Engine Unsupported -->
    <div v-if="!enabled" class="state-banner warning" role="status">
      <AlertTriangle class="w-5 h-5 flex-shrink-0" />
      <div>
        <strong>服务器未启用本地资源功能</strong>
        <p>当前服务端尚未开启内网本地资源调度支持，请联系平台管理员启用该功能。</p>
      </div>
    </div>

    <div v-else-if="!supported" class="state-banner warning" role="status">
      <AlertTriangle class="w-5 h-5 flex-shrink-0" />
      <div>
        <strong>当前引擎暂不支持本地资源</strong>
        <p>支持 OpenCode serve 与 DSH web/host 引擎，当前工作区引擎为 {{ engine || '未知' }}，暂不支持本地资源。</p>
      </div>
    </div>

    <!-- Main Stepper Form -->
    <form v-else class="service-stepper-form" @submit.prevent="persist">
      <!-- Stepper Navigator -->
      <nav class="stepper-nav" aria-label="配置步骤">
        <button
          v-for="step in steps"
          :key="step.id"
          type="button"
          class="stepper-item"
          :class="{ active: currentStep === step.id, completed: currentStep > step.id }"
          :disabled="busy || starting || (step.id > 0 && !connectionChecked)"
          @click="currentStep = step.id"
        >
          <div class="step-indicator">
            <Check v-if="currentStep > step.id" class="w-4 h-4" />
            <component :is="step.icon" v-else class="w-4 h-4" />
          </div>
          <div class="step-meta">
            <span class="step-title">{{ step.title }}</span>
            <span class="step-desc">{{ step.desc }}</span>
          </div>
        </button>
      </nav>

      <!-- Step 0: 网络与服务节点 -->
      <div v-show="currentStep === 0" class="step-content">
        <div class="info-callout">
          <Info class="w-4 h-4 text-sky-500 flex-shrink-0" />
          <span>
            平台将通过局域网直接向下方两个服务地址发起通信。请确保内网 IP 可达且无防火墙阻拦，默认端口为 <strong>4096 (Agent)</strong> 与 <strong>4098 (同机资源服务)</strong>。当前不支持公网部署。
          </span>
        </div>

        <div class="form-grid">

          <div class="form-group">
            <label class="form-label" for="service-url">
              <span>Agent 服务地址</span>
              <span class="required-mark">*</span>
            </label>
            <div class="input-with-affix">
              <span class="input-affix">URL</span>
              <input
                id="service-url"
                v-model="form.service_url"
                type="url"
                required
                placeholder="http://192.168.1.10:4096"
                class="form-input with-affix font-mono"
              />
            </div>
            <p class="form-hint">Agent 智能体核心调度服务，负责接收平台任务并执行模型推理。</p>
          </div>

          <div class="form-group">
            <label class="form-label" for="resource-url">
              <span>同机资源服务地址</span>
              <span class="required-mark">*</span>
            </label>
            <div class="input-with-affix">
              <span class="input-affix">URL</span>
              <input
                id="resource-url"
                v-model="form.resource_service_url"
                type="url"
                required
                placeholder="http://192.168.1.10:4098"
                class="form-input with-affix font-mono"
              />
            </div>
            <p class="form-hint">同机资源服务，负责本地工作区文件读写、Git worktree 检出与工具执行。</p>
          </div>
          <div class="form-group">
            <label class="form-label" for="host-token">
              <span>资源服务配对凭据 (Host Token)</span>
              <span v-if="!selected" class="required-mark">*</span>
            </label>
            <div class="input-with-action">
              <input
                id="host-token"
                v-model="form.host_token"
                :type="showHostToken ? 'text' : 'password'"
                autocomplete="new-password"
                :required="!selected"
                :placeholder="selected ? '留空表示保留原凭据' : '请输入配对 Token'"
                class="form-input font-mono"
              />
              <button
                type="button"
                class="btn-affix-toggle"
                :title="showHostToken ? '隐藏凭据' : '显示凭据'"
                @click="showHostToken = !showHostToken"
              >
                <EyeOff v-if="showHostToken" class="w-4 h-4" />
                <Eye v-else class="w-4 h-4" />
              </button>
            </div>
            <p class="form-hint">修改已有配置时，凭据留空表示保留原密钥。</p>
          </div>

          <div class="form-group">
            <label class="form-label" for="agent-token">
              <span>Agent 访问凭据 (Agent Token)</span>
            </label>
            <div class="input-with-action">
              <input
                id="agent-token"
                v-model="form.agent_token"
                :type="showAgentToken ? 'text' : 'password'"
                autocomplete="new-password"
                :placeholder="selected ? '留空表示保留原凭据' : '请输入访问 Token'"
                class="form-input font-mono"
              />
              <button
                type="button"
                class="btn-affix-toggle"
                :title="showAgentToken ? '隐藏凭据' : '显示凭据'"
                @click="showAgentToken = !showAgentToken"
              >
                <EyeOff v-if="showAgentToken" class="w-4 h-4" />
                <Eye v-else class="w-4 h-4" />
              </button>
            </div>
            <p class="form-hint">Agent 推理服务的访问鉴权凭据。</p>
          </div>

          <div v-if="form.backend === 'opencode'" class="form-group col-span-2">
            <label class="form-label" for="agent-username">
              <span>Agent 用户名</span>
            </label>
            <input
              id="agent-username"
              v-model="form.agent_username"
              type="text"
              placeholder="默认：opencode"
              class="form-input font-mono"
            />
            <p class="form-hint">OpenCode 引擎认证时使用的用户名，默认为 opencode。</p>
          </div>
        </div>
      </div>

      <!-- Step 1: 工作区目录 -->
      <div v-show="currentStep === 1" class="step-content">
        <div class="info-callout">
          <Folder class="w-4 h-4 text-sky-500 flex-shrink-0" />
          <span>
            配置任务独立 worktree 的存放目录。
          </span>
        </div>

        <div class="form-grid">
          <div class="form-group col-span-2">
            <label class="form-label" for="workspace-root">
              <span>本地工作区根目录</span>
              <span class="required-mark">*</span>
            </label>
            <div class="input-with-action">
              <input
                id="workspace-root"
                v-model="form.workspace_root"
                type="text"
                required
                placeholder="例如：G:/workspaces 或 /Users/name/workspaces"
                class="form-input font-mono"
              />
              <button
                v-if="desktop?.git?.selectDirectory"
                type="button"
                class="btn-affix-action"
                @click="selectWorkspaceRoot"
              >
                <Folder class="w-4 h-4" />
                <span>选择目录</span>
              </button>
            </div>
            <p class="form-hint">任务执行时将在此目录下创建独立的 worktree 副本，保存时将自动向同机资源服务授权此工作区目录 (allowed_roots)。</p>
          </div>

        </div>
      </div>

      <!-- Step 2: 代码仓库本地映射 -->
      <div v-show="currentStep === 2" class="step-content">
        <div class="info-callout">
          <FolderGit2 class="w-4 h-4 text-sky-500 flex-shrink-0" />
          <span>
            当前工作区包含 <strong>{{ form.repositories.length }}</strong> 个代码仓库。默认复用本地仓库映射，也可为当前服务指定独立目录。创建任务时将在独立 worktree 中运行。
          </span>
        </div>

        <div v-if="!form.repositories.length" class="empty-repos">
          <p>当前工作区没有关联任何仓库，无需配置本地映射。</p>
        </div>

        <div v-else class="repo-mappings-list">
          <div
            v-for="mapping in form.repositories"
            :key="mapping.repository_id"
            class="repo-card"
          >
            <div class="repo-card-header">
              <div class="repo-title">
                <span class="dot-indicator"></span>
                <span class="repo-id font-mono">{{ mapping.configured_git_url || mapping.repository_id }}</span>
              </div>
            </div>

            <div class="repo-card-body">
              <div class="form-group col-span-2">
                <template v-if="repoMappings.shared(mapping.repository_id)">
                  <p class="form-hint">{{ independentRepos[mapping.repository_id] ? '当前服务使用独立目录，不修改本地仓库映射。' : '已复用本地仓库映射，无需重复配置目录。' }}</p>
                  <button v-if="!independentRepos[mapping.repository_id]" type="button" class="btn-secondary" data-testid="custom-repo" @click="independentRepos[mapping.repository_id] = true">自定义其他目录</button>
                  <button v-else type="button" class="btn-secondary" data-testid="reuse-repo" @click="repoMappings.reuse(mapping)">恢复复用本地仓库映射</button>
                </template>
                <template v-else>
                  <p class="form-hint">尚未设置本地仓库映射。填写后可同步设置，或独立设置，仅用于当前服务。</p>
                  <button type="button" class="btn-secondary" data-testid="sync-repo" :disabled="!!syncingRepo || !mapping.local_path || !mapping.configured_git_url" @click="synchronizeRepo(mapping)">{{ syncingRepo === mapping.repository_id ? '同步中…' : '同步设置本地仓库映射' }}</button>
                </template>
              </div>
              <div class="form-group">
                <label class="form-label" :for="`service-repo-git-remote-${mapping.repository_id}`">
                  <span>个人仓库 Git 地址</span>
                  <span class="required-mark">*</span>
                </label>
                <LocalGitRemoteSelect
                  v-model="mapping.configured_git_url"
                  :id="`service-repo-git-remote-${mapping.repository_id}`"
                  :repo-path="mapping.local_path"
                  :preferred-url="repoMappings.workspaceRemoteFor(mapping.repository_id)"
                  :disabled="!!repoMappings.shared(mapping.repository_id) && !independentRepos[mapping.repository_id]"
                  required
                  test-id="repo-git-url"
                />
              </div>

              <div class="form-group">
                <label class="form-label">
                  <span>本机仓库目录 (Local Path)</span>
                  <span class="required-mark">*</span>
                </label>
                <div class="input-with-action">
                  <input
                    :value="!independentRepos[mapping.repository_id] && repoMappings.shared(mapping.repository_id) ? repoMappings.shared(mapping.repository_id)?.local_path : mapping.local_path"
                    :readonly="!!repoMappings.shared(mapping.repository_id) && !independentRepos[mapping.repository_id]"
                    @input="repoMappings.setLocalPath(mapping, ($event.target as HTMLInputElement).value)"
                    data-testid="repo-path"
                    type="text"
                    required
                    placeholder="例如：G:/workspaces/my-repo"
                    class="form-input font-mono"
                  />
                  <button
                    v-if="desktop?.git?.selectDirectory && (!repoMappings.shared(mapping.repository_id) || independentRepos[mapping.repository_id])"
                    type="button"
                    class="btn-affix-action"
                    @click="selectRepoPath(mapping)"
                  >
                    <Folder class="w-4 h-4" />
                    <span>选择目录</span>
                  </button>
                </div>
                <p class="form-hint">本地仓库目录必须是包含 .git 的有效仓库，保存时将自动向同机资源服务授权 (allowed_roots)。</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Feedback Messages -->
      <div v-if="saveFeedback && !error" class="feedback-banner success" role="status" data-testid="save-feedback">
        <CheckCircle2 class="w-5 h-5" />
        <span>{{ saveFeedback }}</span>
      </div>
      <div v-if="serviceStarted && !error" class="feedback-banner success" role="status">
        <CheckCircle2 class="w-5 h-5" />
        <span>服务已启动，地址与凭据已填写。</span>
      </div>
      <div v-if="error" class="feedback-banner error" role="alert">
        <AlertCircle class="w-4 h-4 flex-shrink-0" />
        <span>{{ error }}</span>
      </div>

      <div v-if="currentStep === 0 && connectionChecked" class="feedback-banner success" role="status">
        <CheckCircle2 class="w-4 h-4 flex-shrink-0" />
        <span>服务地址与网络检测通过，已自动保存，可继续下一步。</span>
      </div>

      <!-- Footer Action Toolbar -->
      <footer class="stepper-footer">
        <div class="footer-left">
          <button
            v-if="currentStep > 0"
            type="button"
            class="btn-secondary"
            @click="currentStep--"
          >
            <ChevronLeft class="w-4 h-4" />
            <span>上一步</span>
          </button>
        </div>

        <div class="footer-right">
          <button
            v-if="currentStep < 2"
            type="button"
            class="btn-primary"
            :disabled="busy || starting || !connectionChecked"
            @click="currentStep++"
          >
            <span>下一步</span>
            <ChevronRight class="w-4 h-4" />
          </button>

          <button
            v-if="currentStep === 0"
            type="button"
            class="btn-secondary"
            :disabled="busy || starting"
            @click="check"
          >
            <RefreshCw class="w-4 h-4" :class="{ spin: busy }" />
            <span>检测</span>
          </button>

          <button
            v-if="desktop?.resources"
            v-show="currentStep === 0"
            type="button"
            class="btn-desktop-start"
            :disabled="busy || starting"
            title="启动本地服务并填写地址与凭据"
            @click="startLocal"
          >
            <Loader2 v-if="starting" class="w-4 h-4 spin" />
            <Play v-else class="w-4 h-4 fill-current" />
            <span>{{ starting ? '启动中…' : '一键启动并配置' }}</span>
          </button>

          <button
            v-if="currentStep === 2"
            type="submit"
            class="btn-primary"
            :disabled="busy || starting || !connectionChecked"
          >
            <Check class="w-4 h-4" />
            <span>保存配置</span>
          </button>
        </div>
      </footer>
    </form>
  </section>
</template>

<style scoped>
.local-service-section {
  padding: 1.75rem 2rem;
  border-radius: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.8);
}

:global(.dark) .local-service-section {
  background: rgba(30, 41, 59, 0.7);
  border-color: rgba(51, 65, 85, 0.7);
}

/* Header */
.section-header {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
}

:global(.dark) .section-header {
  border-bottom-color: rgba(51, 65, 85, 0.8);
}

@media (min-width: 768px) {
  .section-header {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.icon-wrapper {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
  padding: 0.75rem;
  border-radius: 12px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.2);
  flex-shrink: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.title-gradient-small {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

:global(.dark) .title-gradient-small {
  background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: #64748b;
  font-size: 0.875rem;
  margin-top: 0.25rem;
  line-height: 1.5;
}

:global(.dark) .subtitle {
  color: #94a3b8;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.65rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 700;
}

.status-ready {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid rgba(5, 150, 105, 0.2);
}

:global(.dark) .status-ready {
  background: rgba(6, 78, 59, 0.4);
  color: #34d399;
}

.status-error {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid rgba(220, 38, 38, 0.2);
}

:global(.dark) .status-error {
  background: rgba(127, 29, 29, 0.4);
  color: #f87171;
}

.status-idle {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid rgba(100, 116, 139, 0.2);
}

:global(.dark) .status-idle {
  background: rgba(30, 41, 59, 0.6);
  color: #94a3b8;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.profile-select-wrapper {
  position: relative;
  min-width: 190px;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.profile-current-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.55rem;
  border: 1px solid rgba(5, 150, 105, 0.22);
  border-radius: 9999px;
  background: #ecfdf5;
  color: #047857;
  font-size: 0.72rem;
  font-weight: 700;
  white-space: nowrap;
}

.btn-desktop-start {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.15rem;
  border-radius: 0.75rem;
  font-size: 0.875rem;
  font-weight: 600;
  background: linear-gradient(135deg, #f59e0b, #ea580c);
  color: #ffffff;
  border: 1px solid transparent;
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.25);
  cursor: pointer;
  white-space: nowrap;
  outline: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

:global(.dark) .btn-desktop-start {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.btn-desktop-start:hover:not(:disabled) {
  background: linear-gradient(135deg, #d97706, #c2410c);
  box-shadow: 0 4px 12px rgba(234, 88, 12, 0.35);
  transform: translateY(-1px);
}

:global(.dark) .btn-desktop-start:hover:not(:disabled) {
  background: linear-gradient(135deg, #fbbf24, #ea580c);
}

.btn-desktop-start:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(234, 88, 12, 0.2);
}

.btn-desktop-start:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* Stepper Navigation */
.stepper-nav {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.75rem;
  background: #f8fafc;
  padding: 0.5rem;
  border-radius: 1rem;
  border: 1px solid #e2e8f0;
}

:global(.dark) .stepper-nav {
  background: #0f172a;
  border-color: #334155;
}

.stepper-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 0.85rem;
  border-radius: 0.75rem;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}

.stepper-item:hover:not(.active) {
  background: rgba(14, 165, 233, 0.05);
}

.stepper-item.active {
  background: #ffffff;
  border-color: rgba(14, 165, 233, 0.4);
  box-shadow: 0 2px 8px rgba(14, 165, 233, 0.08);
}

:global(.dark) .stepper-item.active {
  background: #1e293b;
  border-color: rgba(14, 165, 233, 0.5);
}

.step-indicator {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 0.8rem;
  font-weight: 700;
  background: #e2e8f0;
  color: #64748b;
  transition: all 0.2s;
}

:global(.dark) .step-indicator {
  background: #334155;
  color: #94a3b8;
}

.stepper-item.active .step-indicator {
  background: #0ea5e9;
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.3);
}

.stepper-item.completed .step-indicator {
  background: #10b981;
  color: #ffffff;
}

.step-meta {
  display: flex;
  flex-direction: column;
}

.step-title {
  font-size: 0.825rem;
  font-weight: 700;
  color: #1e293b;
}

:global(.dark) .step-title {
  color: #f1f5f9;
}

.step-desc {
  font-size: 0.725rem;
  color: #64748b;
}

:global(.dark) .step-desc {
  color: #94a3b8;
}

/* Callout */
.info-callout {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 0.85rem;
  padding: 0.75rem 1rem;
  color: #0369a1;
  font-size: 0.825rem;
  line-height: 1.5;
}

:global(.dark) .info-callout {
  background: rgba(14, 165, 233, 0.1);
  border-color: rgba(14, 165, 233, 0.25);
  color: #38bdf8;
}

/* Form Layout */
.service-stepper-form {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.step-content {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.25rem;
}

.col-span-2 {
  grid-column: 1 / -1;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.form-label {
  font-size: 0.825rem;
  font-weight: 700;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

:global(.dark) .form-label {
  color: #cbd5e1;
}

.required-mark {
  color: #ef4444;
}

.form-hint {
  font-size: 0.75rem;
  color: #64748b;
  margin: 0;
  line-height: 1.4;
}

:global(.dark) .form-hint {
  color: #94a3b8;
}

.form-input {
  width: 100%;
  padding: 0.65rem 0.85rem;
  border-radius: 0.75rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #1e293b;
  font-size: 0.875rem;
  outline: none;
  transition: all 0.2s;
  box-sizing: border-box;
}

:global(.dark) .form-input {
  background: #0f172a;
  border-color: #334155;
  color: #f1f5f9;
}

.form-input:focus {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.input-with-affix {
  position: relative;
  display: flex;
  align-items: center;
}

.input-affix {
  position: absolute;
  left: 0.75rem;
  font-size: 0.75rem;
  font-weight: 700;
  color: #94a3b8;
  pointer-events: none;
}

.form-input.with-affix {
  padding-left: 2.75rem;
}

.input-with-action {
  display: flex;
  gap: 0.5rem;
}

.input-with-action .form-input {
  flex: 1;
}

.btn-affix-action {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.65rem 0.85rem;
  border-radius: 0.75rem;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}

:global(.dark) .btn-affix-action {
  background: #1e293b;
  border-color: #334155;
  color: #e2e8f0;
}

.btn-affix-action:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.btn-affix-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  border-radius: 0.75rem;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

:global(.dark) .btn-affix-toggle {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

.btn-affix-toggle:hover {
  color: #0ea5e9;
  border-color: #0ea5e9;
}

/* Repositories Cards */
.repo-mappings-list {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.repo-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.85rem;
  padding: 1rem;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  transition: border-color 0.2s;
}

:global(.dark) .repo-card {
  background: rgba(15, 23, 42, 0.5);
  border-color: #334155;
}

.repo-card:hover {
  border-color: #94a3b8;
}

.repo-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.repo-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.dot-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}

.repo-id {
  font-size: 0.825rem;
  font-weight: 700;
  color: #1e293b;
}

:global(.dark) .repo-id {
  color: #f1f5f9;
}

.repo-card-body {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.empty-repos {
  padding: 2rem;
  text-align: center;
  border: 1px dashed #cbd5e1;
  border-radius: 0.85rem;
  color: #64748b;
  font-size: 0.875rem;
}

/* State and Feedback Banners */
.state-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-radius: 0.85rem;
  font-size: 0.875rem;
  line-height: 1.5;
}

.state-banner.warning {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #b45309;
}

:global(.dark) .state-banner.warning {
  background: rgba(180, 83, 9, 0.15);
  border-color: rgba(245, 158, 11, 0.3);
  color: #fbbf24;
}

.feedback-banner {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.75rem 1rem;
  border-radius: 0.75rem;
  font-size: 0.825rem;
  font-weight: 500;
}

.feedback-banner.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}

:global(.dark) .feedback-banner.error {
  background: rgba(185, 28, 28, 0.15);
  border-color: rgba(239, 68, 68, 0.3);
  color: #f87171;
}

.feedback-banner.success {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #047857;
}

:global(.dark) .feedback-banner.success {
  background: rgba(4, 120, 87, 0.15);
  border-color: rgba(16, 185, 129, 0.3);
  color: #34d399;
}

/* Footer Toolbar */
.stepper-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(226, 232, 240, 0.8);
  flex-wrap: wrap;
}

:global(.dark) .stepper-footer {
  border-top-color: rgba(51, 65, 85, 0.8);
}

.footer-left,
.footer-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.btn-primary,
.btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.15rem;
  border-radius: 0.75rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  outline: none;
}

.btn-primary {
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  color: #ffffff;
  border: 1px solid transparent;
  box-shadow: 0 2px 8px rgba(14, 165, 233, 0.25);
}

.btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #0284c7 0%, #1d4ed8 100%);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.35);
}

.btn-secondary {
  background: #f8fafc;
  color: #475569;
  border: 1px solid #cbd5e1;
}

:global(.dark) .btn-secondary {
  background: #1e293b;
  border-color: #334155;
  color: #e2e8f0;
}

.btn-secondary:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #1e293b;
}

:global(.dark) .btn-secondary:hover:not(:disabled) {
  background: #334155;
  color: #ffffff;
}

.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.font-mono {
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border-width: 0;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
