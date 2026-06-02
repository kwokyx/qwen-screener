import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '../api/auth'
import { useChatHistoryStore } from './chatHistory'
import { useNotificationsStore } from './notifications'
import { useWatchlistStore } from './watchlist'

const PRIVATE_STORAGE_KEYS = [
  'qwen.watchlist.v1',
  'qwen.chat.history.v1',
  'qwen.chat.activeSession.v1',
  'qwen.notifications.v1',
  'qwen.results.agent.v1',
]

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  function clearLocalPrivateState() {
    for (const key of PRIVATE_STORAGE_KEYS) {
      localStorage.removeItem(key)
      sessionStorage.removeItem(key)
    }
    try { useWatchlistStore().clear() } catch {}
    try { useChatHistoryStore().clear() } catch {}
    try { useNotificationsStore().clear() } catch {}
  }

  async function syncUserState() {
    try { await useWatchlistStore().syncFromServer() } catch { /* 静默 */ }
    try { await useChatHistoryStore().syncFromServer() } catch { /* 静默 */ }
    try { await useNotificationsStore().syncFromServer() } catch { /* 静默 */ }
  }

  async function login(username, password) {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    clearLocalPrivateState()

    const data = await authApi.login(username, password)
    token.value = data.access_token
    user.value = data.user
    localStorage.setItem('token', data.access_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    await syncUserState()
    return data
  }

  async function register(username, password, email) {
    return authApi.register(username, password, email || null)
  }

  async function fetchMe() {
    if (!token.value) return null
    const data = await authApi.me()
    user.value = data
    localStorage.setItem('user', JSON.stringify(data))
    return data
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    clearLocalPrivateState()
  }

  return { token, user, login, register, fetchMe, syncUserState, logout }
})
