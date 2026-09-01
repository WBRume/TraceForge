export type DesktopGitCommandResult = {
  ok: boolean
  stdout: string
  stderr: string
  exitCode?: number
}

export type DesktopGitStatusEntry = {
  code: string
  path: string
}

export type DesktopGitStatus = {
  isClean: boolean
  raw: string
  entries: DesktopGitStatusEntry[]
  unmergedFiles: string[]
}

export type DesktopDirectorySelection = {
  canceled: boolean
  path: string | null
}

export type DesktopPatchApplyResult = DesktopGitCommandResult & {
  conflictedFiles: string[]
}

export type DesktopConfig = {
  serverUrl: string
  token: string | null
  onboardingCompleted: boolean
  repoMappings: Record<string, DesktopRepoMapping>
}

export type DesktopRepoMapping = {
  workspaceId: string
  remoteUrl: string
  localPath: string
  lastVerificationCommand?: string | null
  updatedAt: string
}

export type DesktopRunCommandRequest = {
  cwd: string
  command: string
  args?: string[]
}

export type DesktopRunCommandResponse = {
  runId: string
  pid: number | null
  startedAt: string
}

export type DesktopCommandOutputEvent = {
  runId: string
  stream: 'stdout' | 'stderr'
  text: string
  at: string
}

export type DesktopCommandExitEvent = {
  runId: string
  command: string
  code: number | null
  signal: string | null
  error?: string
  durationMs: number
  finishedAt: string
}

export type DesktopSaveResult = {
  saved: boolean
  canceled: boolean
  savedPath: string | null
  error?: string
}

export type DesktopSaveRequest = {
  suggestedName: string
  data: ArrayBuffer | Uint8Array
  mimeType?: string
}

export type DesktopOAuthStartPayload = {
  provider: string
  intent: OAuthIntent
  clientType: OAuthClientType
}

export type DesktopOAuthStartResult = {
  ticket?: string
  status?: string
  error?: string
}

export type DesktopOAuthTicketListener = (payload: DesktopOAuthStartResult) => void

import type { OAuthClientType, OAuthIntent } from './oauth'

export type SddDesktopApi = {
  platform: string
  download: {
    save: (payload: DesktopSaveRequest) => Promise<DesktopSaveResult>
  }
  git: {
    selectDirectory: () => Promise<DesktopDirectorySelection>
    validateGitRepo: (repoPath: string) => Promise<{ ok: boolean; stdout: string; stderr: string }>
    getRemoteUrl: (repoPath: string) => Promise<{ remoteUrl: string }>
    getStatus: (repoPath: string) => Promise<DesktopGitStatus>
    fetchOrigin: (repoPath: string) => Promise<DesktopGitCommandResult>
    checkoutBranch: (repoPath: string, branch: string) => Promise<DesktopGitCommandResult>
    pullFfOnly: (repoPath: string, branch?: string) => Promise<DesktopGitCommandResult>
    createLocalBranch: (repoPath: string, branch: string) => Promise<DesktopGitCommandResult>
    applyPatchWithThreeWay: (repoPath: string, patchText: string) => Promise<DesktopPatchApplyResult>
    getHeadSha: (repoPath: string) => Promise<{ headSha: string }>
  }
  process: {
    runCommand: (payload: DesktopRunCommandRequest) => Promise<DesktopRunCommandResponse>
    cancelCommand: (runId: string) => Promise<{ ok: boolean; message?: string }>
    onCommandOutput: (listener: (event: DesktopCommandOutputEvent) => void) => () => void
    onCommandExit: (listener: (event: DesktopCommandExitEvent) => void) => () => void
  }
  config: {
    getConfig: () => Promise<DesktopConfig>
    setConfig: (payload: Partial<Pick<DesktopConfig, 'serverUrl' | 'token' | 'onboardingCompleted'>>) => Promise<DesktopConfig>
    getRepoMapping: (payload: { workspaceId: string; remoteUrl: string }) => Promise<DesktopRepoMapping | null>
    setRepoMapping: (payload: Omit<DesktopRepoMapping, 'updatedAt'>) => Promise<DesktopRepoMapping>
    removeRepoMapping: (payload: { workspaceId: string; remoteUrl: string }) => Promise<{ removed: boolean }>
  }
  system: {
    openExternal: (url: string) => Promise<{ ok: boolean }>
    openPath: (path: string) => Promise<{ ok: boolean }>
  }
  oauth?: {
    start: (payload: DesktopOAuthStartPayload) => Promise<DesktopOAuthStartResult>
    onTicket: (listener: DesktopOAuthTicketListener) => () => void
  }
}

declare global {
  interface Window {
    sddDesktop?: SddDesktopApi
  }
}

export {}
