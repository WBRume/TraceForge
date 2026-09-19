import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const renderMock = vi.fn(() => ({ promise: Promise.resolve() }))
const fakeDoc = {
  numPages: 2,
  getPage: async () => ({
    getViewport: ({ scale }: { scale: number }) => ({ width: 612 * scale, height: 792 * scale }),
    render: renderMock,
  }),
}
type GetDocumentArg = { data: unknown }
const getDocumentMock = vi.fn((src: GetDocumentArg) => ({ promise: Promise.resolve(fakeDoc), ...src }))

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: {},
  getDocument: (...args: [GetDocumentArg]) => getDocumentMock(...args),
}))
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }))
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('@/utils/api', () => ({
  default: { get: vi.fn(async () => ({ data: new Uint8Array([1, 2, 3]).buffer })) },
}))

import PdfCanvas from '@/components/doc-review/PdfCanvas.vue'

describe('PdfCanvas', () => {
  beforeEach(() => {
    renderMock.mockClear()
    getDocumentMock.mockClear()
  })

  it('拉取原文件字节并逐页渲染 canvas', async () => {
    const wrapper = mount(PdfCanvas, {
      props: { wsId: 'ws-1', assetId: 'a-1', versionId: null },
    })
    await flushPromises()
    expect(getDocumentMock).toHaveBeenCalledTimes(1)
    expect((getDocumentMock.mock.calls[0][0] as GetDocumentArg).data).toBeInstanceOf(Uint8Array)
    expect(wrapper.findAll('canvas').length).toBe(2)
  })
})
