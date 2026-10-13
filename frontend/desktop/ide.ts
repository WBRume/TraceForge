import { realpath, stat } from 'node:fs/promises'
import { isAbsolute, relative, resolve, sep } from 'node:path'
import { pathToFileURL } from 'node:url'
import { spawn } from 'node:child_process'

export type IdePreference = { editor: 'vscode' | 'idea' | 'pycharm'; executable?: string; launchers?: { idea?: string; pycharm?: string } }
export type IdeLocation = { workspaceId: string; remoteUrl: string; path: string; line?: number; column?: number }

export async function ideTarget(root: string, request: IdeLocation) {
  if (!isAbsolute(root) || !request.path || /[\\:\x00]/.test(request.path)
    || request.path.split('/').some(part => !part || part === '.' || part === '..' || part.toLowerCase() === '.git')) {
    throw new Error('IDE_PATH_INVALID')
  }
  const base = await realpath(root)
  let file: string
  try { file = await realpath(resolve(base, request.path)) } catch { throw new Error('IDE_FILE_MISSING') }
  const child = relative(base, file)
  if (!child || isAbsolute(child) || child === '..' || child.startsWith(`..${sep}`)) throw new Error('IDE_PATH_OUTSIDE_REPOSITORY')
  if (!(await stat(file)).isFile()) throw new Error('IDE_FILE_MISSING')
  const line = request.line ?? 1, column = request.column ?? 1
  if (![line, column].every(value => Number.isSafeInteger(value) && value > 0 && value <= 10_000_000)) throw new Error('IDE_POSITION_INVALID')
  return { file, line, column }
}

export function vscodeUrl(target: Awaited<ReturnType<typeof ideTarget>>) {
  const path = pathToFileURL(target.file).pathname
  return `vscode://file${path}:${target.line}:${target.column}`
}

export async function launchIde(preference: IdePreference, target: Awaited<ReturnType<typeof ideTarget>>, openUrl: (url: string) => Promise<unknown>) {
  if (preference.editor === 'vscode') { await openUrl(vscodeUrl(target)); return }
  if (!['idea', 'pycharm'].includes(preference.editor)) throw new Error('IDE_EDITOR_INVALID')
  const executable = preference.executable?.trim() || (process.platform === 'win32' ? `${preference.editor}64.exe` : preference.editor)
  // Arguments are separate and never interpreted by a shell. Windows launchers
  // must be native executables, not command strings or .cmd/.bat wrappers.
  if (/\.(cmd|bat)$/i.test(executable) || executable.includes('\0')) throw new Error('IDE_EXECUTABLE_INVALID')
  await new Promise<void>((done, reject) => {
    const child = spawn(executable, ['--line', String(target.line), target.file], { shell: false, detached: true, stdio: 'ignore', windowsHide: true })
    child.once('error', () => reject(new Error('IDE_LAUNCH_FAILED')))
    child.once('spawn', () => { child.unref(); done() })
  })
}
