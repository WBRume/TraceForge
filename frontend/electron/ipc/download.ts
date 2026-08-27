import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { writeFile } from 'node:fs/promises'
import { extname, join } from 'node:path'

export type DesktopSaveRequest = {
  suggestedName: string
  data: ArrayBuffer | Uint8Array
  mimeType?: string
}

export type DesktopSaveReply = {
  saved: boolean
  canceled: boolean
  savedPath: string | null
  error?: string
}

const SAFE_NAME = /[\\/:*?"<>|]+/g

const downloadFilters = (suggestedName: string) => {
  const ext = extname(suggestedName || '').toLowerCase()
  if (ext === '.zip') {
    return [
      { name: 'ZIP 压缩包', extensions: ['zip'] },
      { name: '所有文件', extensions: ['*'] },
    ]
  }
  return [
    { name: 'Markdown', extensions: ['md', 'markdown'] },
    { name: '所有文件', extensions: ['*'] },
  ]
}

/**
 * 文件另存为：弹出原生「保存」对话框，用户确认保存位置并完成写盘后返回。
 *
 * - canceled=true：用户取消，未写盘，渲染层不应触发「标记已导出」；
 * - saved=true：文件已写入用户选择的本地路径，渲染层可触发确认接口。
 */
export const registerDownloadIpc = () => {
  ipcMain.handle(
    'sdd:download:save',
    async (event, payload: DesktopSaveRequest): Promise<DesktopSaveReply> => {
      try {
        const suggestedName = String(payload?.suggestedName || 'download.bin')
          .replace(SAFE_NAME, '_')
          .slice(0, 200)
        const win = BrowserWindow.fromWebContents(event.sender) ?? undefined
        const options: Electron.SaveDialogOptions = {
          title: '保存文件',
          defaultPath: join(app.getPath('downloads'), suggestedName),
          filters: downloadFilters(suggestedName),
          properties: ['showOverwriteConfirmation', 'createDirectory'],
        }
        const result = win
          ? await dialog.showSaveDialog(win, options)
          : await dialog.showSaveDialog(options)
        if (result.canceled || !result.filePath) {
          return { saved: false, canceled: true, savedPath: null }
        }

        const data = payload?.data
        const bytes =
          data instanceof ArrayBuffer
            ? new Uint8Array(data)
            : data instanceof Uint8Array
              ? data
              : null
        if (bytes === null) {
          return { saved: false, canceled: false, savedPath: null, error: 'invalid-data' }
        }
        await writeFile(result.filePath, Buffer.from(bytes))
        return { saved: true, canceled: false, savedPath: result.filePath }
      } catch (err) {
        return {
          saved: false,
          canceled: false,
          savedPath: null,
          error: err instanceof Error ? err.message : String(err),
        }
      }
    },
  )
}