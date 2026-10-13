import { afterEach, describe, expect, it, vi } from 'vitest'
import { proxyRefs, ref } from 'vue'
import { useOpenInIde } from '../useOpenInIde'
import type { CollaborationContext } from '../useCollaborationPresentation'

const bridge = vi.hoisted(() => ({ openInIde: vi.fn() }))
vi.mock('@/utils/runtime', () => ({ getSddDesktop: () => ({ system: bridge }) }))
afterEach(() => vi.clearAllMocks())

describe('IDE navigation without collaboration', () => {
  function setup() {
    const context = proxyRefs({ participating: ref(false), view: ref({ page: 'files' }),
      state: ref({ repositories: ['api', 'web'].map(id => ({ task_repository_id: id, repo_url: `https://test/${id}` })) }),
      mappings: ref({ api: { local_path: 'G:/api' }, web: { local_path: 'G:/web' } }),
    }) as unknown as CollaborationContext
    return { context, ide: useOpenInIde(() => context, () => 'workspace') }
  }
  it('dispatches the clicked repository and line, independent of sync ownership', async () => {
    const { ide } = setup()
    bridge.openInIde.mockResolvedValue({ ok: true })
    await ide.open('web', 'shared.txt', 23, 4)
    expect(bridge.openInIde).toHaveBeenCalledWith({ workspaceId: 'workspace', remoteUrl: 'https://test/web', path: 'shared.txt', line: 23, column: 4 })
  })
  it('opens mapping settings when unmapped, without starting collaboration', async () => {
    const { ide, context } = setup()
    context.mappings = {}
    await ide.open('api', 'shared.txt', 3)
    expect(context.view.page).toBe('settings')
    expect(bridge.openInIde).not.toHaveBeenCalled()
  })
  it('keeps a missing local file as an explicit choice to receive, never downloads automatically', async () => {
    const { ide } = setup()
    bridge.openInIde.mockRejectedValue(new Error('IDE_FILE_MISSING'))
    await ide.open('api', 'new.txt')
    expect(ide.error.value).toContain('先接收云端代码')
  })
})
