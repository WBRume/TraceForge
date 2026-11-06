import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const { target } = JSON.parse(readFileSync(resolve('dist-desktop-host/runtime.json'), 'utf8'))
export const executable = resolve(`src-tauri/binaries/traceforge-node-${target}${target.includes('windows') ? '.exe' : ''}`)
export const hostArguments = ['--disable-warning=ExperimentalWarning', resolve('dist-desktop-host/host.js')]
