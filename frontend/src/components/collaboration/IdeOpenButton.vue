<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { ElPopover } from 'element-plus'
import { Check, ChevronDown, Settings } from '@/components/icons'
import { ideOptions, useIdePreference, type IdeEditor } from '@/composables/collaboration/useIdePreference'

defineProps<{ title?: string }>()
const emit = defineEmits<{ open: []; error: [message: string] }>()
const { preference, selected, busy, load, save } = useIdePreference(message => emit('error', message))
const visible = ref(false), configuring = ref(false), executable = ref('')
const menu = ref<HTMLElement>(), trigger = ref<HTMLButtonElement>()

async function showMenu() {
  configuring.value = false
  await load()
  await nextTick()
  if (visible.value) menu.value?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus()
}
async function choose(editor: IdeEditor) {
  if (!await save(editor)) return
  visible.value = false
  await nextTick()
  trigger.value?.focus()
  emit('open')
}
function configure() {
  executable.value = preference.value.executable || ''
  configuring.value = true
  nextTick(() => menu.value?.querySelector('input')?.focus())
}
async function savePath() {
  if (await save(selected.value.value, executable.value)) configuring.value = false
}
function close(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  event.preventDefault(); event.stopPropagation()
  visible.value = false
  nextTick(() => trigger.value?.focus())
}
function navigate(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const items = [...menu.value?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') || []]
  const current = items.indexOf(document.activeElement as HTMLButtonElement)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
    : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
  items[next]?.focus()
}
</script>

<template>
  <div class="ide-open-button" @keydown="close">
    <button class="open-file" type="button" :disabled="busy" :title="title" :aria-label="`在 ${selected.label} 中打开`" @click="emit('open')">
      <span class="ide-mark" :class="selected.value" aria-hidden="true">{{ selected.mark }}</span><span>打开</span>
    </button>
    <ElPopover v-model:visible="visible" role="dialog" placement="bottom-end" trigger="click" :hide-after="0" :width="264" popper-class="ide-picker-popover" @show="showMenu">
      <template #reference><button ref="trigger" class="choose-ide" type="button" aria-label="选择 IDE" aria-haspopup="dialog" :aria-expanded="visible" :disabled="busy" @keydown.down.prevent="visible = true"><ChevronDown :size="13" /></button></template>
      <div ref="menu" class="ide-menu" @keydown="close">
        <div class="menu-caption">在本地 IDE 中打开</div>
        <div role="menu" aria-label="选择 IDE" @keydown="navigate">
          <button v-for="option in ideOptions" :key="option.value" type="button" role="menuitemradio" :aria-checked="selected.value === option.value" :disabled="busy" @click="choose(option.value)">
            <span class="ide-mark" :class="option.value" aria-hidden="true">{{ option.mark }}</span>
            <span class="ide-name">{{ option.label }}</span><Check v-if="selected.value === option.value" :size="14" class="selected-check" />
          </button>
        </div>
        <div v-if="selected.value !== 'vscode'" class="launcher-settings">
          <button v-if="!configuring" type="button" class="configure-ide" @click="configure"><Settings :size="13" />配置 {{ selected.label }} 启动路径</button>
          <form v-else @submit.prevent="savePath">
            <label for="ide-launcher-path">{{ selected.label }} 启动程序</label>
            <input id="ide-launcher-path" v-model="executable" placeholder="完整路径，留空使用系统命令" :disabled="busy" />
            <div class="path-actions"><button type="button" @click="configuring = false">取消</button><button type="submit" :disabled="busy">保存</button></div>
          </form>
        </div>
        <p class="local-hint">打开映射仓库中的本地文件</p>
      </div>
    </ElPopover>
  </div>
</template>

<style scoped>
.ide-open-button { display: inline-flex; height: var(--comparison-control-height, 30px); box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; flex: none; }
button { font: inherit; cursor: pointer; }
.open-file, .choose-ide { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 0; background: transparent; color: #334155; font-size: 12px; }
.open-file { padding: 0 9px; border-radius: 5px 0 0 5px; }
.choose-ide { width: 27px; border-left: 1px solid #e2e8f0; border-radius: 0 5px 5px 0; }
.open-file:hover, .choose-ide:hover, .choose-ide[aria-expanded=true] { background: #f1f5f9; }
button:focus-visible, input:focus-visible { outline: 2px solid #0284c7; outline-offset: 1px; }
button:disabled { opacity: .5; cursor: default; }
.ide-mark { width: 20px; height: 20px; display: inline-grid; place-items: center; flex: none; font: 700 9px/1 system-ui; border-radius: 4px; letter-spacing: -.5px; }
.vscode { color: #0078b9; background: #e0f2fe; }
.idea { color: #7e22ce; background: #f3e8ff; }
.pycharm { color: #15803d; background: #dcfce7; }
.ide-menu { font-size: 12px; color: #334155; }
.menu-caption { font-size: 11px; color: #64748b; padding: 2px 8px 8px; }
[role=menu] button { display: flex; align-items: center; width: 100%; gap: 10px; padding: 8px; border: 0; background: transparent; color: inherit; border-radius: 5px; text-align: left; }
[role=menu] button:hover, [role=menu] button:focus-visible { background: #f1f5f9; }
.ide-name { flex: 1; }.selected-check { color: #0284c7; }
.launcher-settings { border-top: 1px solid #e2e8f0; margin-top: 6px; padding: 8px 4px 0; }
.configure-ide { border: 0; background: none; color: #64748b; display: flex; gap: 7px; align-items: center; padding: 4px; font-size: 11px; }
form label { display: block; margin-bottom: 6px; font-size: 11px; }
input { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 5px; padding: 7px; font-size: 11px; }
.path-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.path-actions button { border: 1px solid #e2e8f0; border-radius: 4px; background: #fff; padding: 3px 9px; color: #475569; font-size: 11px; }
.path-actions button[type=submit] { background: #0284c7; border-color: #0284c7; color: #fff; }
.local-hint { color: #94a3b8; font-size: 11px; margin: 8px 8px 0; }
:global(.ide-picker-popover) { max-width: calc(100vw - 24px); padding: 8px !important; border-radius: 9px !important; }
</style>
