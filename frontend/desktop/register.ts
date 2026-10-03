import { registerLocalResourcesIpc } from '../electron/ipc/localResources'
import { registerConfigIpc } from '../electron/ipc/config'
import { registerDownloadIpc } from '../electron/ipc/download'
import { registerGitIpc } from '../electron/ipc/git'
import { registerOauthIpc } from '../electron/ipc/oauth'
import { registerPatchIpc } from '../electron/ipc/patch'
import { registerProcessIpc } from '../electron/ipc/process'
import { registerSystemIpc } from '../electron/ipc/system'
import { registerAttentionIpc } from '../electron/ipc/attention'
import { registerWebhooksIpc } from '../electron/ipc/webhooks'

export function registerDesktopCommands() {
  registerLocalResourcesIpc()
  registerConfigIpc()
  registerDownloadIpc()
  registerGitIpc()
  registerOauthIpc()
  registerPatchIpc()
  registerProcessIpc()
  registerSystemIpc()
  registerAttentionIpc()
  registerWebhooksIpc()
}
