import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { startAlertEngine } from './services/alertEngine'
import { useWatchlistStore } from './stores/watchlist'
import { useChatHistoryStore } from './stores/chatHistory'
import { useAiStatusStore } from './stores/aiStatus'

import './assets/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

// 启动后：登录态下从后端拉自选 / 对话历史合并到本地
useWatchlistStore().syncFromServer()
useChatHistoryStore().syncFromServer()

// 启动价格预警轮询
startAlertEngine()

// 启动 AI 上游可用性探测（每 2 分钟一次）
useAiStatusStore().startAutoProbe()
