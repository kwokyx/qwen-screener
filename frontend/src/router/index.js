import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { public: true, label: '01 · 行情 Dashboard' } },
  { path: '/chat', name: 'chat', component: () => import('../views/Chat.vue'), meta: { public: true, label: '02 · 千问对话筛选' } },
  { path: '/results', name: 'results', component: () => import('../views/Results.vue'), meta: { public: true, label: '03 · 因子筛选 + 结果列表' } },
  { path: '/detail/:code?', name: 'detail', component: () => import('../views/Detail.vue'), meta: { public: true, label: '04 · 股票详情 + 千问解读' } },
  { path: '/portfolio', name: 'portfolio', component: () => import('../views/Portfolio.vue'), meta: { public: true, label: '05 · 自选 / 持仓' } },
  { path: '/strategy', name: 'strategy', component: () => import('../views/Strategy.vue'), meta: { public: true, label: '06 · 策略回测' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.token) {
    return { name: 'login', query: { next: to.fullPath } }
  }
})

export default router
