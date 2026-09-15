import { contextBridge, ipcRenderer } from 'electron'

const desktopApi = {
  platform: process.platform,
  download: {
    save: (payload: { suggestedName: string; data: ArrayBuffer | Uint8Array; mimeType?: string }) =>
      ipcRenderer.invoke('sdd:download:save', payload),
  },
  git: {
    selectDirectory: () => ipcRenderer.invoke('sdd:git:select-directory'),
    validateGitRepo: (repoPath: string) => ipcRenderer.invoke('sdd:git:validate-repo', { repoPath }),
    getRemoteUrl: (repoPath: string) => ipcRenderer.invoke('sdd:git:get-remote-url', { repoPath }),
    getStatus: (repoPath: string) => ipcRenderer.invoke('sdd:git:get-status', { repoPath }),
    fetchOrigin: (repoPath: string) => ipcRenderer.invoke('sdd:git:fetch-origin', { repoPath }),
    checkoutBranch: (repoPath: string, branch: string) =>
      ipcRenderer.invoke('sdd:git:checkout-branch', { repoPath, branch }),
    pullFfOnly: (repoPath: string, branch?: string) =>
      ipcRenderer.invoke('sdd:git:pull-ff-only', { repoPath, branch }),
    createLocalBranch: (repoPath: string, branch: string) =>
      ipcRenderer.invoke('sdd:git:create-local-branch', { repoPath, branch }),
    applyPatchWithThreeWay: (repoPath: string, patchText: string) =>
      ipcRenderer.invoke('sdd:git:apply-patch-with-three-way', { repoPath, patchText }),
    getHeadSha: (repoPath: string) => ipcRenderer.invoke('sdd:git:get-head-sha', { repoPath }),
  },
  process: {
    runCommand: (payload: unknown) => ipcRenderer.invoke('sdd:process:run-command', payload),
    cancelCommand: (runId: string) => ipcRenderer.invoke('sdd:process:cancel-command', { runId }),
    onCommandOutput: (listener: (event: unknown) => void) => {
      const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown) => listener(payload)
      ipcRenderer.on('sdd:process:output', wrapped)
      return () => ipcRenderer.removeListener('sdd:process:output', wrapped)
    },
    onCommandExit: (listener: (event: unknown) => void) => {
      const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown) => listener(payload)
      ipcRenderer.on('sdd:process:exit', wrapped)
      return () => ipcRenderer.removeListener('sdd:process:exit', wrapped)
    },
  },
  config: {
    getConfig: () => ipcRenderer.invoke('sdd:config:get'),
    setConfig: (payload: unknown) => ipcRenderer.invoke('sdd:config:set', payload),
    getRepoMapping: (payload: unknown) => ipcRenderer.invoke('sdd:config:get-repo-mapping', payload),
    setRepoMapping: (payload: unknown) => ipcRenderer.invoke('sdd:config:set-repo-mapping', payload),
    removeRepoMapping: (payload: unknown) => ipcRenderer.invoke('sdd:config:remove-repo-mapping', payload),
  },
  system: {
    openExternal: (url: string) => ipcRenderer.invoke('sdd:system:open-external', { url }),
    openPath: (path: string) => ipcRenderer.invoke('sdd:system:open-path', { path }),
  },
  oauth: {
    start: (payload: { provider: string; intent: 'login' | 'bind'; clientType: 'web' | 'desktop' }) =>
      ipcRenderer.invoke('sdd:oauth:start', payload),
    onTicket: (listener: (payload: { ticket?: string; status?: string; error?: string }) => void) => {
      const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown) => listener(payload as { ticket?: string; status?: string; error?: string })
      ipcRenderer.on('sdd:oauth:ticket', wrapped)
      return () => ipcRenderer.removeListener('sdd:oauth:ticket', wrapped)
    },
  },
}

contextBridge.exposeInMainWorld('sddDesktop', desktopApi)
