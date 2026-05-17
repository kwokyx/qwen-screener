import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { startAlertEngine } from './services/alertEngine'
import { useWatchlistStore } from './stores/watchlist'
import { useChatHistoryStore } from './stores/chatHistory'
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

// 启动后：登录态下从后端拉自选 / 对话历史合并到本地
useWatchlistStore().syncFromServer()
useChatHistoryStore().syncFromServer()

// 启动价格预警轮询
startAlertEngine()

// 启动 AI 上游可用性探测（每 2 分钟一次）
useAiStatusStore().startAutoProbe()
