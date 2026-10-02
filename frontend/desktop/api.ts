import type { SddDesktopApi } from '../src/types/sddDesktop'

export type DesktopBridge = {
  runtime: 'electron' | 'tauri'
  platform: string
  invoke<T>(channel: string, payload?: unknown): Promise<T>
  subscribe(channel: string, listener: (payload: any) => void): () => void
}

/** One command and event contract for both desktop shells. */
export function createDesktopApi(bridge: DesktopBridge): SddDesktopApi {
  const invoke = <T>(name: string, payload?: unknown) => bridge.invoke<T>(`sdd:${name}`, payload)
  const repo = <T>(name: string, repoPath: string, extra = {}) => invoke<T>(`git:${name}`, { repoPath, ...extra })
  return {
    runtime: bridge.runtime,
    platform: bridge.platform,
    resources: {
      configureRoots: payload => invoke('resources:configure-roots', payload),
      start: payload => invoke('resources:start', payload),
    },
    download: { save: payload => invoke('download:save', payload) },
    git: {
      selectDirectory: () => invoke('git:select-directory'),
      validateGitRepo: path => repo('validate-repo', path),
      getFetchRemotes: path => repo('get-remotes', path),
      preparePatchWorktree: payload => invoke('git:prepare-patch-worktree', payload),
      getRemoteUrl: path => repo('get-remote-url', path),
      getStatus: path => repo('get-status', path),
      fetchOrigin: path => repo('fetch-origin', path),
      checkoutBranch: (path, branch) => repo('checkout-branch', path, { branch }),
      pullFfOnly: (path, branch) => repo('pull-ff-only', path, { branch }),
      createLocalBranch: (path, branch) => repo('create-local-branch', path, { branch }),
      applyPatchWithThreeWay: (path, patchText) => repo('apply-patch-with-three-way', path, { patchText }),
      getHeadSha: path => repo('get-head-sha', path),
    },
    process: {
      runCommand: payload => invoke('process:run-command', payload),
      cancelCommand: runId => invoke('process:cancel-command', { runId }),
      onCommandOutput: listener => bridge.subscribe('sdd:process:output', listener),
      onCommandExit: listener => bridge.subscribe('sdd:process:exit', listener),
    },
    config: {
      getConfig: () => invoke('config:get'),
      setConfig: payload => invoke('config:set', payload),
      getRepoMapping: payload => invoke('config:get-repo-mapping', payload),
      setRepoMapping: payload => invoke('config:set-repo-mapping', payload),
      removeRepoMapping: payload => invoke('config:remove-repo-mapping', payload),
    },
    system: {
      openExternal: url => invoke('system:open-external', { url }),
      openPath: path => invoke('system:open-path', { path }),
    },
    oauth: {
      start: payload => invoke('oauth:start', payload),
      onTicket: listener => bridge.subscribe('sdd:oauth:ticket', listener),
    },
  }
}
