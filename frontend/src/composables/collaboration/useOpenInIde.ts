import { shallowRef } from 'vue'
import { getSddDesktop } from '@/utils/runtime'
import type { CollaborationContext } from './useCollaborationPresentation'

export function useOpenInIde(context: () => CollaborationContext, workspaceId: () => string) {
  const desktop = getSddDesktop(), error = shallowRef('')
  const hint = (repositoryId: string) => !desktop?.system.openInIde ? '请在桌面客户端中打开本地 IDE'
    : !context().mappings[repositoryId] ? '先配置此仓库的本地映射' : '在 IDE 中打开本地文件（本地内容可能与云端不同）'
  async function open(repositoryId: string, path: string, line = 1, column = 1) {
    error.value = ''
    if (!desktop?.system.openInIde) { error.value = hint(repositoryId); return }
    const c = context(), repo = c.state?.repositories.find(row => row.task_repository_id === repositoryId)
    if (!repo || !c.mappings[repositoryId]) { c.view.page = 'settings'; return }
    try { await desktop.system.openInIde({ workspaceId: workspaceId(), remoteUrl: repo.repo_url, path, line, column }) }
    catch (reason) {
      const message = String(reason)
      error.value = message.includes('IDE_FILE_MISSING') ? '本地尚无此文件。可先接收云端代码，再在 IDE 中打开。'
        : message.includes('IDE_MAPPING_REQUIRED') ? '请重新配置此仓库的本地映射。'
        : message.includes('IDE_LAUNCH_FAILED') ? '无法启动 IDE，请在“打开”菜单中检查 IDE 启动路径。'
        : message.includes('IDE_PATH') ? '文件路径不在映射仓库内，无法打开。'
        : '无法打开 IDE，请确认 IDE 已安装，并检查“打开”菜单中的启动路径。'
    }
  }
  return { error, hint, open, available: Boolean(desktop?.system.openInIde) }
}
