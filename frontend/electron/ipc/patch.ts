import { app, ipcMain } from 'electron'
import { mkdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
import { listUnmergedFiles, runGit } from './git'

type ApplyPatchPayload = {
  repoPath?: string
  patchText?: string
}

const assertPatchPayload = (payload: ApplyPatchPayload) => {
  const repoPath = String(payload?.repoPath || '').trim()
  const patchText = String(payload?.patchText || '')
  if (!repoPath) {
    throw new Error('Repository path is required')
  }
  if (!patchText.trim()) {
    throw new Error('Patch content is required')
  }
  return { repoPath, patchText }
}

export const registerPatchIpc = () => {
  ipcMain.handle('sdd:git:apply-patch-with-three-way', async (_event, payload: ApplyPatchPayload) => {
    const { repoPath, patchText } = assertPatchPayload(payload)
    const tempDir = join(app.getPath('temp'), 'sdd-native-patches')
    await mkdir(tempDir, { recursive: true })
    const patchPath = join(tempDir, `${randomUUID()}.patch`)

    try {
      await writeFile(patchPath, patchText, 'utf8')
      const result = await runGit(repoPath, ['apply', '--3way', patchPath], {
        allowFailure: true,
        timeoutMs: 300_000,
      })
      const conflictedFiles = result.ok ? [] : await listUnmergedFiles(repoPath)
      return {
        ok: result.ok,
        stdout: result.stdout,
        stderr: result.stderr,
        exitCode: result.exitCode,
        conflictedFiles,
      }
    } finally {
      await rm(patchPath, { force: true }).catch(() => undefined)
    }
  })
}
