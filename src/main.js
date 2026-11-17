import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { ElMessage } from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles.css'
import App from './App.vue'
import { router } from './router'
import { applyTheme, currentTheme } from './theme'

applyTheme(currentTheme())

const app = createApp(App)

// 全局异常兜底：148 处手写 toast 之外的漏网异常不能静默失败。
// 提示用户 + 留 console 现场；防抖避免同一条错误连点刷屏。
let lastErrorText = ''
let lastErrorAt = 0
function reportGlobalError(prefix, error) {
  const text = `${prefix}：${error?.message || error}`
  console.error(text, error)
  const now = Date.now()
  if (text === lastErrorText && now - lastErrorAt < 3000) return
  lastErrorText = text
  lastErrorAt = now
  ElMessage.error(text)
}
app.config.errorHandler = (err, instance, info) => {
  reportGlobalError('页面异常', err)
}
window.addEventListener('unhandledrejection', (event) => {
  reportGlobalError('操作未完成', event.reason)
})

app.use(ElementPlus, { locale: zhCn })
app.use(router)
app.mount('#app')
