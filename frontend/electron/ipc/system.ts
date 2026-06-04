import { ipcMain, shell } from 'electron'

export const registerSystemIpc = () => {
  ipcMain.handle('sdd:system:open-external', async (_event, payload: { url?: string }) => {
    const url = String(payload?.url || '').trim()
    if (!/^https?:\/\//i.test(url)) {
      throw new Error('Only http(s) URLs can be opened externally')
    }
    await shell.openExternal(url)
    return { ok: true }
  })

  ipcMain.handle('sdd:system:open-path', async (_event, payload: { path?: string }) => {
    const path = String(payload?.path || '').trim()
    if (!path) {
      throw new Error('Path is required')
    }
    const error = await shell.openPath(path)
    if (error) {
      throw new Error(error)
    }
    return { ok: true }
  })
}
