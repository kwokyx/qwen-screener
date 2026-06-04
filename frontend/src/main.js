import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { startAlertEngine } from './services/alertEngine'
import { useAuthStore } from './stores/auth'
import { useAiStatusStore } from './stores/aiStatus'
import { toast } from './stores/toast'

import './assets/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)

// Vue 全局错误兜底：渲染 / 生命周期 / watcher 抛的异常都先 log + toast 提示，
// 让用户知道"出错了但页面还活着"。组件树本身的崩溃由 ErrorBoundary 接管。
app.config.errorHandler = (err, _vm, info) => {
  console.error('[Vue errorHandler]', info, err)
  try { toast.error(err?.message || '页面遇到错误，请刷新重试') } catch {}
}

app.mount('#app')

// 启动后：登录态下确认 token，并同步自选 / 对话历史 / 通知。
const auth = useAuthStore()
if (auth.token) {
  auth.fetchMe()
    .then(() => auth.syncUserState())
    .catch(() => {})
}

// 价格预警不抢首屏资源；首轮轮询由引擎延后执行。
startAlertEngine()

// AI 健康探测放到首屏之后，避免启动时的上游网络抖动拖慢行情页。
const startAiProbe = () => useAiStatusStore().startAutoProbe()
if ('requestIdleCallback' in window) {
  window.requestIdleCallback(startAiProbe, { timeout: 8_000 })
} else {
  window.setTimeout(startAiProbe, 4_000)
}
