import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '../api/auth'
import { useChatHistoryStore } from './chatHistory'
import { useNotificationsStore } from './notifications'
import { useWatchlistStore } from './watchlist'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  async function login(username, password) {
    const data = await authApi.login(username, password)
    token.value = data.access_token
    user.value = data.user
    localStorage.setItem('token', data.access_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    // 登录成功后双向同步：拉服务端自选 + 把本地独有的项推上去
    try { await useWatchlistStore().syncFromServer() } catch { /* 静默 */ }
    try { await useChatHistoryStore().syncFromServer() } catch { /* 静默 */ }
    try { await useNotificationsStore().syncFromServer() } catch { /* 静默 */ }
    return data
  }

  async function register(username, password, email) {
    return authApi.register(username, password, email || null)
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    // 清掉内存 + localStorage 中的用户态数据，避免下个账号在同一浏览器登录时混入上个账号数据
    try { useWatchlistStore().clear() } catch {}
    try { useChatHistoryStore().clear() } catch {}
    try { useNotificationsStore().clear() } catch {}
  }

  return { token, user, login, register, logout }
})
