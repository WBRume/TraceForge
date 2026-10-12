// Browser-only transport fixture: real renderer components and coordinator, synthetic API/native data.
// It is deliberately outside the production entry and is not evidence of filesystem correctness.
import { createApp, defineComponent, ref } from 'vue/dist/vue.esm-bundler.js'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '@/assets/main.css'
import i18n from '@/i18n'
import api from '@/utils/api'
import { useAuthStore } from '@/stores/auth'
import { useLocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import { saveRepoPreferences } from '@/composables/localRepoPreferences'
import ApplyPatchDrawer from '@/components/local-agent/ApplyPatchDrawer.vue'
import ChatExecutionInput from '@/components/chat/ChatExecutionInput.vue'
import CollaborationEntry from '@/components/collaboration/CollaborationEntry.vue'
import CollaborationInputStatus from '@/components/collaboration/CollaborationInputStatus.vue'

const repository = (id: string, branch: string, path: string, hash: string) => ({ task_repository_id: id, repository_id: id, repo_url: `https://example.test/${id}.git`, repo_slug: id, rel_path: id, branch_name: branch, base_commit_sha: 'd273bc715119940c27f3bd8e', files: [{ path, sha256: hash.repeat(64), size: 27, mode: '100644' }] })
const repositories = [repository('api', 'release/2.x', 'src/auth.py', 'a'), repository('web', 'feature/login', 'src/login.ts', 'b')]
const baseline = { protocol_version: 1, task_id: 'fixture-task', snapshot_id: 'initial', workspace_revision: 1, session_generation: 1, session_revision: 1, repository_set_digest: 'fixture-digest', source: 'INITIAL', repositories }
let state: any = { ...baseline, driver_user_id: 'fixture-user', enabled: false, sync_phase: 'OFF', state_version: 1, lease_epoch: 1, binding_id: 'fixture-binding', input_snapshot_id: 'initial', progress_snapshot_id: null, conflicts: [] }
let output: any = baseline
let status: any = { directory_mode: 'MAPPED', task_id: baseline.task_id, task_root: 'G:/TraceForge/tasks/fixture-task', baseline, received: baseline, target: null, manifest: baseline, state: 'READY', repositories: repositories.map(repo => ({ ...repo, local_worktree_path: `G:/repos/${repo.repo_slug}`, mapped_repo_root: `G:/repos/${repo.repo_slug}` })), conflicts: [], local_changes: [] }
const contents: Record<string, string> = { a: 'def authenticate(token):\n    return check(token)\n', b: 'export const timeout = 3000\n', c: 'def authenticate(token):\n    return check(token, retry=True)\n', d: 'def authenticate(token):\n    return check(token, audit=True)\n' }
let sent = false
let backups: any[] = []
let sceneSequence = 0
const identity = { client_id: 'fixture-client', instance_id: 'fixture-instance' }
const deliveryFailure = new URLSearchParams(location.search).has('delivery-failure')
let deliveryBroken = deliveryFailure, deliveryAttempts = 0
const mappingRecovery = new URLSearchParams(location.search).has('mapping-recovery')
let mappingBlocked = new URLSearchParams(location.search).has('dirty')
let preparationDelay = 0
let prepared = !mappingRecovery
if (mappingRecovery) {
  state = { ...state, ...identity, enabled: true, sync_phase: 'DELIVERY_PENDING', driver_connected: true }
  saveRepoPreferences('fixture-workspace', 'fixture-user', [])
}
if (deliveryFailure) state = { ...state, ...identity, enabled: true, sync_phase: 'DELIVERY_PENDING', driver_connected: true }
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))
const savedMappings = new Map<string, any>()
Object.assign(window, { sddDesktop: {
  runtime: 'electron', platform: 'win32',
  config: { getRepoMapping: async ({ remoteUrl }: any) => savedMappings.get(remoteUrl) || (mappingRecovery ? null : ({ localPath: `G:/repos/${remoteUrl.includes('api') ? 'api' : 'web'}`, gitRemoteUrl: remoteUrl })), setRepoMapping: async (mapping: any) => { savedMappings.set(mapping.remoteUrl, mapping); return mapping }, getConfig: async () => ({ token: null, repoMappings: {} }) },
  git: { selectDirectory: async () => ({ canceled: false, path: 'G:/repos/selected' }), validateGitRepo: async () => ({ ok: true }), getFetchRemotes: async () => [] },
  system: { openPath: async () => ({ ok: true }) },
  download: { save: async () => ({ saved: true, canceled: false, savedPath: 'fixture-export' }) },
  collaboration: { execute: async ({ kind, payload }: any) => {
    if (kind === 'inspect_mappings') return { ready: !mappingBlocked, checks: repositories.map((repo, i) => ({ task_repository_id: repo.task_repository_id,
      local_path: `G:/repos/${repo.repo_slug}`, expected_head: repo.base_commit_sha, local_head: mappingBlocked && !i ? 'f'.repeat(40) : repo.base_commit_sha,
      local_branch: repo.branch_name, clean: !mappingBlocked || !!i, changes: mappingBlocked && !i ? [' M src/auth.py', '?? notes.txt'] : [],
      errors: mappingBlocked && !i ? ['HEAD_MISMATCH', 'WORKTREE_DIRTY'] : [] })) }
    if (kind === 'describe') return { mapped_repositories: 1, ...identity, task_root: status.task_root, repositories: status.repositories }
    if (kind === 'status' && !prepared) throw new Error("Error invoking remote method 'sdd:collaboration:execute': ENOENT: no such file or directory, open 'G:/profile/collaboration/bindings/fixture-task.json'")
    if (kind === 'prepare') { await new Promise(resolve => setTimeout(resolve, preparationDelay)); prepared = true }
    if (kind === 'missing_objects') return { missing: [] }
    if (kind === 'read_object') return { content: btoa(contents[payload.sha256[0]] || '// unchanged\n') }
    if (kind === 'capture') return { manifest: status.manifest, status, objects: [], input_cut_seq: 1 }
    if (kind === 'backups') return { backup_directory: 'G:/TraceForge/private/backups', backups }
    if (kind === 'accept_input') { status = { ...status, baseline: payload.target, received: payload.target, local_changes: [] }; return clone(status) }
    if (kind === 'reconcile') {
      deliveryAttempts++
      if (deliveryBroken) throw new Error("Error invoking remote method 'sdd:collaboration:execute': Error: LOCAL_CONTENT_OBJECT_MISSING")
      if (payload.target.source === 'INITIAL') return clone(status)
      if (payload.preview) return { ...clone(status), preview_conflicts: status.conflicts }
      return clone(status)
    }
    if (kind === 'restore') {
      backups.push(...payload.selected.map((file: any) => ({ operation_id: 'restore-fixture', task_repository_id: file.task_repository_id, path: file.path, sha256: 'd'.repeat(64), state: 'RESTORED', backup_path: `G:/TraceForge/private/backups/${file.path}` })))
      const selected = new Set(payload.selected.map((file: any) => file.task_repository_id + ':' + file.path))
      const remaining = status.conflicts.filter((file: any) => !selected.has(file.task_repository_id + ':' + file.path))
      const restoredManifest = clone(status.manifest)
      restoredManifest.repositories.forEach((repo: any) => { repo.files = repo.files.map((file: any) => selected.has(repo.task_repository_id + ':' + file.path) ? output.repositories.find((row: any) => row.task_repository_id === repo.task_repository_id).files.find((row: any) => row.path === file.path) : file) })
      status = { ...status, state: remaining.length ? 'CONFLICT_PENDING' : 'READY', manifest: restoredManifest, baseline: output, received: output, conflicts: remaining, conflict_set_id: remaining.length ? 'conflict-1' : null, local_changes: [] }
    }
    return clone(status)
  } },
} })
api.defaults.adapter = async config => {
  let data: any = clone(state)
  const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
  if (config.url?.endsWith('/enable')) { state = { ...state, ...body, enabled: true, sync_phase: 'DELIVERY_PENDING' }; data = clone(state) }
  else if (config.url?.endsWith('/receipt')) { state.sync_phase = body.conflicts.length ? 'CONFLICT_PENDING' : 'READY'; data = clone(state) }
  else if (config.url?.endsWith('/disable')) { state = { ...state, enabled: false, sync_phase: 'OFF' }; data = clone(state) }
  else if (config.url?.endsWith('/handoff')) { output = { ...body.manifest, source: 'HUMAN_HANDOFF', snapshot_id: 'handoff1', workspace_revision: 3 }; state = { ...state, input_snapshot_id: 'handoff1', snapshot_id: 'handoff1', workspace_revision: 3 }; data = clone(state) }
  else if (config.url?.endsWith('/objects/missing')) data = { missing: [] }
  else if (config.url?.includes('/snapshots/')) data = clone(config.url.endsWith('/initial') ? baseline : output)
  else if (config.url?.includes('/change-proposals')) data = null
  return { data, status: 200, statusText: 'OK', headers: {}, config }
}
const app = createApp(defineComponent({
  components: { ApplyPatchDrawer, ChatExecutionInput, CollaborationEntry, CollaborationInputStatus },
  setup() {
    useAuthStore().setUser({ id: 'fixture-user', email: 'fixture@example.test', display_name: 'Fixture' })
    const task = { id: 'fixture-task', name: '修复登录过期后的重试逻辑', workspace_id: 'fixture-workspace', execution_location: 'SERVER', status: 'CODING' }
    const collaboration = useLocalCollaboration({ workspaceId: () => 'fixture-workspace', task: () => task })
    const show = ref(mappingRecovery || deliveryFailure), draft = ref('继续优化登录重试逻辑')
    Object.assign(window, { mappingFixture: {
      repairDelivery: () => { deliveryBroken = false },
      deliveryAttempts: () => deliveryAttempts,
      clean: () => { mappingBlocked = false },
      delay: (milliseconds: number) => { preparationDelay = milliseconds },
      save: () => saveRepoPreferences('fixture-workspace', 'fixture-user', repositories.map(repo => ({ repository_id: repo.repository_id, local_path: `G:/repos/${repo.repo_slug}`, configured_git_url: repo.repo_url }))),
      controller: () => collaboration,
      state: () => ({ phase: collaboration.phase.value, preparationRequired: collaboration.preparationRequired.value, error: collaboration.error.value, mappings: collaboration.mappings.value }),
    } })
    async function scene(name: string) {
      if (!state.enabled) await collaboration.enable()
      const snapshotId = `scene-${name}-${++sceneSequence}`
      if (['ready', 'local', 'offline', 'observer'].includes(name)) {
        const edited = clone(baseline)
        edited.repositories[0].files[0].sha256 = 'd'.repeat(64)
        output = { ...baseline, source: 'AGENT_OUTPUT', snapshot_id: snapshotId }
        status = { ...status, state: 'READY', baseline: output, received: output, target: output, manifest: name === 'local' ? edited : output, conflicts: [], conflict_set_id: null, local_changes: name === 'local' ? [{ task_repository_id: 'api', path: 'src/auth.py', base: repositories[0].files[0], local: edited.repositories[0].files[0] }] : [] }
        state = { ...state, ...identity, client_id: name === 'observer' ? 'other-client' : identity.client_id, driver_connected: name !== 'offline', sync_phase: 'READY', snapshot_id: output.snapshot_id, progress_snapshot_id: null, conflicts: [] }
        await collaboration.refresh(); show.value = true; return
      }
      const cloudRepos = clone(repositories); cloudRepos.forEach(repo => { repo.files[0].sha256 = 'c'.repeat(64) })
      output = { ...baseline, snapshot_id: snapshotId, workspace_revision: name === 'running' ? 1 : 2, source: name === 'running' ? 'PROGRESS' : 'AGENT_OUTPUT', repositories: cloudRepos }
      const localRepos = clone(repositories); localRepos.forEach(repo => { repo.files[0].sha256 = 'd'.repeat(64) })
      const conflict = { task_repository_id: 'api', path: 'src/auth.py', expected_sha256: 'd'.repeat(64), base: repositories[0].files[0], local: localRepos[0].files[0], cloud: cloudRepos[0].files[0], reason: 'BOTH_CHANGED' }
      status = { ...status, manifest: { ...baseline, repositories: localRepos }, target: name === 'running' ? null : output, conflict_set_id: 'conflict-1', conflicts: [conflict, { ...conflict, task_repository_id: 'web', path: 'src/login.ts', local: localRepos[1].files[0], base: repositories[1].files[0], cloud: cloudRepos[1].files[0] }], local_changes: [{ task_repository_id: 'api', path: 'src/auth.py', base: conflict.base, local: conflict.local }] }
      state = { ...state, ...identity, driver_connected: true, sync_phase: name === 'running' ? 'RUNNING' : 'DELIVERY_PENDING', snapshot_id: name === 'running' ? 'initial' : snapshotId, progress_snapshot_id: name === 'running' ? snapshotId : null }
      await collaboration.refresh(); show.value = true
    }
    Object.assign(window, { uiFixture: { scene, show: () => { show.value = true } } })
    return { task, collaboration, show, draft, scene, sent, submit: () => { sent = true } }
  },
  template: `<main style="height:100vh;padding:30px;background:#f6f8fb;display:flex;flex-direction:column;gap:22px"><small>实际 Vue 组件交互验证 · 模拟传输数据 · 不操作本地文件</small><header style="display:flex;gap:12px;align-items:center"><h2 style="flex:1">{{task.name}}</h2><CollaborationEntry :controller="collaboration" @open="show=true"/></header><div style="display:flex;gap:12px"><button @click="scene('running')">模拟执行中</button><button @click="scene('conflict')">模拟最终冲突</button></div><section style="flex:1">云端会话内容区域。关闭抽屉后协同继续工作。</section><CollaborationInputStatus :controller="collaboration" @open="show=true"/><ChatExecutionInput v-model="draft" :disabled="false" :send-blocked="collaboration.blocked.value" :running="false" :can-interrupt="false" :interrupting="false" placeholder="继续写草稿" send-title="发送" interrupt-title="停止" @submit="submit"/><ApplyPatchDrawer :show="show" :task="task" :workspace="{id:'fixture-workspace'}" :collaboration="collaboration" @close="show=false"/></main>`,
}))
app.use(createPinia()).use(i18n).use(ElementPlus).use(createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })).mount('#app')
