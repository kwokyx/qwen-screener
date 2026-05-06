// 通知中心：保存最近触发的预警和系统消息
// 由 services/alertEngine.js 投递

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

const LS_KEY = 'qwen.notifications.v1'
const MAX = 50

function loadFromLS() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function uid() {
  return Math.random().toString(36).slice(2, 10)
}

export const useNotificationsStore = defineStore('notifications', () => {
  // n = { id, kind: 'alert'|'system', tone: 'up'|'down'|'qwen'|'amber', tag, stock, code, desc, ts, read }
  const items = ref(loadFromLS())

  watch(items, (v) => localStorage.setItem(LS_KEY, JSON.stringify(v)), { deep: true })

  const unreadCount = computed(() => items.value.filter((x) => !x.read).length)

  function push(n) {
    items.value.unshift({
      id: uid(),
      ts: Math.floor(Date.now() / 1000),
      read: false,
      kind: 'alert',
      tone: 'qwen',
      ...n,
    })
    if (items.value.length > MAX) items.value.length = MAX

    // 桌面通知（如已授权）
    try {
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(`${n.tag || '提醒'}：${n.stock || ''}`, {
          body: n.desc,
          tag: n.code || n.tag,
          silent: false,
        })
      }
    } catch {
      /* 忽略 */
    }
  }

  function markRead(id) {
    const x = items.value.find((i) => i.id === id)
    if (x) x.read = true
  }

  function markAllRead() {
    items.value.forEach((x) => (x.read = true))
  }

  function clear() {
    items.value = []
  }

  async function ensurePermission() {
    if (typeof Notification === 'undefined') return 'unsupported'
    if (Notification.permission === 'granted') return 'granted'
    if (Notification.permission === 'denied') return 'denied'
    return await Notification.requestPermission()
  }

  return { items, unreadCount, push, markRead, markAllRead, clear, ensurePermission }
})
