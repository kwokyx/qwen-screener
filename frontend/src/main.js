import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { startAlertEngine } from './services/alertEngine'

import './assets/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

// 启动价格预警轮询（pinia 安装之后才能用 store）
startAlertEngine()
