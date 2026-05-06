import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { startAlertEngine } from './services/alertEngine'
import { useWatchlistStore } from './stores/watchlist'

import './assets/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

// 启动后：把后端自选合并到本地（如果已登录）
useWatchlistStore().syncFromBackend()

// 启动价格预警轮询
startAlertEngine()
