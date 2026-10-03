import { ipcMain, setNativeAttention } from '../../desktop/native'

export function registerAttentionIpc() {
  ipcMain.handle('sdd:attention:set', (event, payload: { flash: boolean; hitlCount: number }) => setNativeAttention(event.sender, payload))
}
