import axios from 'axios'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

const PRIVATE_STORAGE_KEYS = [
  'token',
  'user',
  'qwen.watchlist.v1',
  'qwen.chat.history.v1',
  'qwen.chat.activeSession.v1',
  'qwen.notifications.v1',
  'qwen.results.agent.v1',
]

function clearPrivateStorage() {
  for (const key of PRIVATE_STORAGE_KEYS) {
    localStorage.removeItem(key)
    sessionStorage.removeItem(key)
  }
}

function loginRedirectUrl() {
  const current = `${location.pathname}${location.search}${location.hash}`
  const redirect = current && current !== '/login' ? `?redirect=${encodeURIComponent(current)}` : ''
  return `/login${redirect}`
}

client.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      clearPrivateStorage()
      if (location.pathname !== '/login') location.replace(loginRedirectUrl())
    }
    return Promise.reject(err)
  },
)

export default client
