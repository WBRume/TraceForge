import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  confirmRagQueueCaseDownload,
  confirmRagQueueDownload,
  downloadRagQueueCase,
  downloadRagQueueZip,
  saveBlobToDisk,
} from '@/composables/rag/ragOutboxOps'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

const desktopMock = vi.hoisted(() => ({
  desktop: null as null | { download: { save: (...args: unknown[]) => Promise<unknown> } },
  getSddDesktop: () => desktopMock.desktop,
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

vi.mock('@/utils/runtime', () => ({
  getSddDesktop: () => desktopMock.desktop,
}))

// jsdom 的 Blob 未实现 arrayBuffer()，而桌面保存分支依赖它（真实 Chromium/Electron 均有）。
// 用 FileReader 补一个最小 polyfill（直接 await 时可以正常推进）。
if (typeof Blob.prototype.arrayBuffer !== 'function') {
  Blob.prototype.arrayBuffer = function (this: Blob) {
    return new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as ArrayBuffer)
      reader.onerror = () => reject(reader.error)
      reader.readAsArrayBuffer(this)
    })
  }
}

if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => 'blob:fake'
}
URL.revokeObjectURL = () => {}

const MARKDOWN_BLOB = new Blob(['# case'], { type: 'text/markdown' })

describe('ragOutboxOps / 下载-保存-确认标记 流程', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    desktopMock.desktop = null
  })

  it('Electron 保存对话框取消 → { saved:false, canceled:true }（不标记）', async () => {
    desktopMock.desktop = {
      download: {
        save: vi.fn().mockResolvedValue({ saved: false, canceled: true, savedPath: null }),
      },
    }
    const result = await saveBlobToDisk(MARKDOWN_BLOB, 'case.md')
    expect(result).toEqual({ saved: false, canceled: true })
  })

  it('Electron 保存成功（已写盘）→ { saved:true, canceled:false }（可标记）', async () => {
    desktopMock.desktop = {
      download: {
        save: vi.fn().mockResolvedValue({
          saved: true,
          canceled: false,
          savedPath: 'C:/Downloads/case.md',
        }),
      },
    }
    const result = await saveBlobToDisk(MARKDOWN_BLOB, 'case.md')
    expect(result).toEqual({ saved: true, canceled: false })
  })

  it('saveBlobToDisk 把 Blob 字节与建议文件名交给 Electron 主进程', async () => {
    const save = vi.fn().mockResolvedValue({ saved: true, canceled: false, savedPath: '/x' })
    desktopMock.desktop = { download: { save } }
    const blob = new Blob(['hello'], { type: 'text/markdown' })

    await saveBlobToDisk(blob, 'case.md')

    expect(save).toHaveBeenCalledWith({
      suggestedName: 'case.md',
      data: expect.any(ArrayBuffer) as unknown,
      mimeType: 'text/markdown',
    })
  })

  it('queue ZIP 下载：只拉取字节不标记，返回保存结果', async () => {
    apiMock.get.mockResolvedValue({ data: new Blob(['pk'], { type: 'application/zip' }) })
    desktopMock.desktop = {
      download: { save: vi.fn().mockResolvedValue({ saved: true, canceled: false, savedPath: '/q.zip' }) },
    }

    const result = await downloadRagQueueZip('q1', 'RAG-001')

    expect(apiMock.get).toHaveBeenCalledWith(
      '/rag/queues/q1/export.zip',
      expect.objectContaining({ responseType: 'blob' }),
    )
    expect(result).toEqual({ saved: true, canceled: false })
    // 下载函数本身绝不调用确认/标记接口
    expect(apiMock.post).not.toHaveBeenCalled()
  })

  it('单案例 MD 下载：只拉取字节不标记，返回保存结果', async () => {
    apiMock.get.mockResolvedValue({ data: MARKDOWN_BLOB })
    desktopMock.desktop = {
      download: { save: vi.fn().mockResolvedValue({ saved: true, canceled: false, savedPath: '/c.md' }) },
    }

    const result = await downloadRagQueueCase('q1', 'c1', '案例一.md')

    expect(apiMock.get).toHaveBeenCalledWith(
      '/rag/queues/q1/cases/c1/export.md',
      expect.objectContaining({ responseType: 'blob' }),
    )
    expect(result).toEqual({ saved: true, canceled: false })
    expect(apiMock.post).not.toHaveBeenCalled()
  })

  it('confirmRagQueueDownload 仅负责确认标记（幂等确认接口）', async () => {
    apiMock.post.mockResolvedValue({ data: { id: 'q1', status: 'CONSUMED' } })

    const result = await confirmRagQueueDownload('q1')

    expect(apiMock.post).toHaveBeenCalledWith('/rag/queues/q1/export/complete')
    expect(result.status).toBe('CONSUMED')
  })

  it('confirmRagQueueCaseDownload 标记单个案例', async () => {
    apiMock.post.mockResolvedValue({ data: { id: 'c1', status: 'EXPORTED' } })

    const result = await confirmRagQueueCaseDownload('q1', 'c1')

    expect(apiMock.post).toHaveBeenCalledWith('/rag/queues/q1/cases/c1/export/complete')
    expect(result.status).toBe('EXPORTED')
  })
})