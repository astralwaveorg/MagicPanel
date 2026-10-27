<template>
  <div ref="host" class="mp-code-editor" :style="{ height }"></div>
</template>

<script setup>
// 通用代码编辑器：CodeMirror 6 按需懒加载（独立 chunk，不拖累首屏）。
// YAML 自带实时语法校验（js-yaml 是既有依赖），JS/JSON 高亮；
// 供自主维护等编辑场景使用，只读文件不渲染本组件。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as jsYaml from 'js-yaml'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: '' },   // yaml / javascript / json / ''
  readonly: { type: Boolean, default: false },
  height: { type: String, default: '420px' },
})
const emit = defineEmits(['update:modelValue'])

const host = ref(null)
let view = null
let pending = null

function yamlLinter(view) {
  const text = view.state.doc.toString()
  try {
    jsYaml.load(text)
    return []
  } catch (e) {
    const line = (e.mark && e.mark.line) ?? 0
    const pos = view.state.doc.line(Math.min(line + 1, view.state.doc.lines)).from
    return [{
      from: pos,
      to: Math.min(pos + 1, view.state.doc.length),
      severity: 'error',
      message: e.reason || String(e),
    }]
  }
}

/** 校验当前内容（yaml）：合法返回 null，非法返回带行号的错误说明。 */
function validate() {
  if (props.language !== 'yaml') return null
  try {
    jsYaml.load(props.modelValue)
    return null
  } catch (e) {
    const line = ((e.mark && e.mark.line) ?? 0) + 1
    return `YAML 语法错误（第 ${line} 行）：${e.reason || e.message}`
  }
}

defineExpose({ validate })

function langExtension(lang) {
  switch (lang) {
    case 'yaml': return import('@codemirror/lang-yaml').then((m) => m.yaml())
    case 'javascript': return import('@codemirror/lang-javascript').then((m) => m.javascript())
    case 'json': return import('@codemirror/lang-json').then((m) => m.json())
    default: return Promise.resolve([])
  }
}

async function build() {
  const [cmView, cmState, cmCommands, cmLang] = await Promise.all([
    import('@codemirror/view'),
    import('@codemirror/state'),
    import('@codemirror/commands'),
    import('@codemirror/language'),
  ])
  const lang = await langExtension(props.language)
  const { EditorView } = cmView
  const { EditorState } = cmState
  // 语法配色跟主题走：暗色用 oneDark 的配色，亮色用内置默认
  const dark = document.documentElement.classList.contains('dark')
  const highlight = dark
    ? cmLang.syntaxHighlighting((await import('@codemirror/theme-one-dark')).oneDarkHighlightStyle)
    : cmLang.syntaxHighlighting(cmLang.defaultHighlightStyle, true)
  const extensions = [
    EditorState.readOnly.of(props.readonly),
    cmView.lineNumbers(),
    cmView.highlightActiveLine(),
    cmView.highlightActiveLineGutter(),
    highlight,
    cmView.EditorView.updateListener.of((u) => {
      if (u.docChanged) emit('update:modelValue', u.state.doc.toString())
    }),
    // keymap 在 @codemirror/view，history 系列在 @codemirror/commands
    cmView.keymap.of(cmCommands.defaultKeymap),
    cmCommands.history(),
    cmView.keymap.of(cmCommands.historyKeymap),
    ...(lang ? [lang] : []),
    ...(props.language === 'yaml'
      ? [(await import('@codemirror/lint')).linter(yamlLinter)] : []),
    EditorView.theme({
      '&': { fontSize: '12.5px', backgroundColor: 'var(--mp-surface-2)' },
      '.cm-gutters': {
        backgroundColor: 'var(--mp-surface-2)',
        color: 'var(--mp-muted)',
        border: 'none',
        borderRight: '1px solid var(--mp-border)',
      },
      '.cm-content': { padding: '8px 0' },
      '&.cm-focused': { outline: 'none' },
    }),
  ]
  view = new EditorView({
    state: EditorState.create({ doc: props.modelValue, extensions }),
    parent: host.value,
  })
  if (pending !== null) applyDoc(pending)
  pending = null
}

function applyDoc(text) {
  if (!view) return
  if (view.state.doc.toString() === text) return
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } })
}

onMounted(() => { build().catch((e) => console.error('CodeEditor 初始化失败:', e)) })
onBeforeUnmount(() => { view?.destroy(); view = null })

watch(() => props.modelValue, (v) => {
  // 外部赋值（加载文件 / 格式化）同步进编辑器；自身输入不回写
  if (!view) { pending = v; return }
  applyDoc(v)
})
</script>

<style scoped>
.mp-code-editor {
  border: 1px solid var(--mp-border);
  border-radius: 6px;
  overflow: hidden;
}
.mp-code-editor :deep(.cm-editor) { height: 100%; }
.mp-code-editor :deep(.cm-scroller) { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
