import { loader } from '@guolao/vue-monaco-editor'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'

let monacoConfigured = false

export const ensureMonacoViteSetup = () => {
  if (monacoConfigured) return

  // Monaco local workers for Vite bundling mode.
  ;(self as typeof globalThis & {
    MonacoEnvironment?: {
      getWorker: (_moduleId: string, label: string) => Worker
    }
  }).MonacoEnvironment = {
    getWorker(_moduleId: string, label: string): Worker {
      if (label === 'json') return new jsonWorker()
      if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker()
      if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker()
      if (label === 'typescript' || label === 'javascript') return new tsWorker()
      return new editorWorker()
    },
  }

  loader.config({ monaco })
  monacoConfigured = true
}
