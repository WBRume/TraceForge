import { app, ipcMain } from 'electron'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'

type RepoMapping = {
  workspaceId: string
  remoteUrl: string
  localPath: string
  lastVerificationCommand?: string | null
  updatedAt: string
}

export type DesktopConfig = {
  serverUrl: string
  token: string | null
  onboardingCompleted: boolean
  repoMappings: Record<string, RepoMapping>
}

export type RepoMappingEntry = RepoMapping

const DEFAULT_CONFIG: DesktopConfig = {
  serverUrl: 'http://localhost:8000',
  token: null,
  onboardingCompleted: false,
  repoMappings: {},
}

const configPath = () => join(app.getPath('userData'), 'config.json')

const normalizeRemoteUrl = (value: unknown): string => {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const sshMatch = raw.match(/^git@([^:]+):(.+)$/)
  if (sshMatch?.[1] && sshMatch?.[2]) {
    return `${sshMatch[1]}/${sshMatch[2]}`.replace(/\.git$/i, '').replace(/\/+$/, '').toLowerCase()
  }
  try {
    const url = new URL(raw)
    return `${url.host}${url.pathname}`.replace(/\.git$/i, '').replace(/\/+$/, '').toLowerCase()
  } catch {
    return raw.replace(/\.git$/i, '').replace(/\/+$/, '').toLowerCase()
  }
}

const repoMappingKey = (workspaceId: unknown, remoteUrl: unknown): string => {
  const ws = String(workspaceId || '').trim()
  const remote = normalizeRemoteUrl(remoteUrl)
  if (!ws || !remote) {
    throw new Error('workspaceId and remoteUrl are required')
  }
  return `${ws}:${remote}`
}

const normalizeConfig = (raw: Partial<DesktopConfig> | null | undefined): DesktopConfig => ({
  serverUrl: String(raw?.serverUrl || DEFAULT_CONFIG.serverUrl).replace(/\/+$/, ''),
  token: raw?.token ? String(raw.token) : null,
  onboardingCompleted: Boolean(raw?.onboardingCompleted),
  repoMappings: raw?.repoMappings && typeof raw.repoMappings === 'object' ? raw.repoMappings : {},
})

export const readConfig = async (): Promise<DesktopConfig> => {
  try {
    const raw = await readFile(configPath(), 'utf8')
    return normalizeConfig(JSON.parse(raw) as Partial<DesktopConfig>)
  } catch {
    return { ...DEFAULT_CONFIG }
  }
}

const writeConfig = async (config: DesktopConfig): Promise<DesktopConfig> => {
  const path = configPath()
  await mkdir(dirname(path), { recursive: true })
  const normalized = normalizeConfig(config)
  await writeFile(path, `${JSON.stringify(normalized, null, 2)}\n`, 'utf8')
  return normalized
}

export const registerConfigIpc = () => {
  ipcMain.handle('sdd:config:get', async () => readConfig())

  ipcMain.handle('sdd:config:set', async (_event, payload: Partial<DesktopConfig>) => {
    const current = await readConfig()
    return writeConfig({
      ...current,
      ...payload,
      repoMappings: current.repoMappings,
      serverUrl: String(payload?.serverUrl ?? current.serverUrl).replace(/\/+$/, ''),
      token: payload?.token === undefined ? current.token : payload.token ? String(payload.token) : null,
      onboardingCompleted: payload?.onboardingCompleted ?? current.onboardingCompleted,
    })
  })

  ipcMain.handle('sdd:config:get-repo-mapping', async (_event, payload: { workspaceId?: string; remoteUrl?: string }) => {
    const config = await readConfig()
    const key = repoMappingKey(payload?.workspaceId, payload?.remoteUrl)
    return config.repoMappings[key] || null
  })

  ipcMain.handle('sdd:config:set-repo-mapping', async (_event, payload: Partial<RepoMapping>) => {
    const config = await readConfig()
    const key = repoMappingKey(payload?.workspaceId, payload?.remoteUrl)
    const mapping: RepoMapping = {
      workspaceId: String(payload.workspaceId || '').trim(),
      remoteUrl: String(payload.remoteUrl || '').trim(),
      localPath: String(payload.localPath || '').trim(),
      lastVerificationCommand: payload.lastVerificationCommand
        ? String(payload.lastVerificationCommand)
        : null,
      updatedAt: new Date().toISOString(),
    }
    if (!mapping.localPath) {
      throw new Error('localPath is required')
    }
    config.repoMappings[key] = mapping
    await writeConfig(config)
    return mapping
  })

  ipcMain.handle('sdd:config:remove-repo-mapping', async (_event, payload: { workspaceId?: string; remoteUrl?: string }) => {
    const config = await readConfig()
    const key = repoMappingKey(payload?.workspaceId, payload?.remoteUrl)
    const removed = Boolean(config.repoMappings[key])
    delete config.repoMappings[key]
    await writeConfig(config)
    return { removed }
  })
}
