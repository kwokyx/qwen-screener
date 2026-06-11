// 通知中心：保存最近触发的预警和系统消息
// 由 services/alertEngine.js 投递；登录态下镜像到后端 /notifications

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import * as notifApi from '../api/notification'
import { useWatchlistStore } from './watchlist'

const LS_KEY = 'qwen.notifications.v1'
const MAX = 50
const SHANGHAI_DATE = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function isLoggedIn() {
  return !!localStorage.getItem('token')
}

function loadFromLS() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? normalizeItems(arr) : []
  } catch {
    return []
  }
}

function uid() {
  return Math.random().toString(36).slice(2, 10)
}

function stockDisplayName(code, preferred = '') {
  const name = String(preferred || '').trim()
  if (name && name !== code) return name
  if (!code) return name
  try {
    return useWatchlistStore().get(code)?.name || name || code
  } catch {
    return name || code
  }
}

function dayKey(ts) {
  const seconds = Number(ts)
  const date = Number.isFinite(seconds) ? new Date(seconds * 1000) : new Date()
  return SHANGHAI_DATE.format(date)
}

function dedupeKey(n) {
  if ((n.kind || 'alert') !== 'alert') return ''
  if (!n.code || !n.tag) return ''
  return `${n.code}|${n.tag}|${dayKey(n.ts)}`
}

function normalizeItems(list) {
  const sorted = [...list].sort((a, b) => Number(b?.ts || 0) - Number(a?.ts || 0))
  const seen = new Set()
  const out = []
  for (const item of sorted) {
    const key = dedupeKey(item)
    if (key && seen.has(key)) continue
    if (key) seen.add(key)
    out.push(item)
    if (out.length >= MAX) break
  }
  return out
}

/** 服务端行 → 本地 item。 */
function fromServer(r) {
  const ts = r.fired_at ? Math.floor(new Date(r.fired_at).getTime() / 1000) : Math.floor(Date.now() / 1000)
  const code = r.stock_code || ''
  return {
    id: uid(),
    serverId: r.id,
    kind: r.kind || 'alert',
    tone: r.tone || 'qwen',
    tag: r.title || '提醒',
    stock: stockDisplayName(code, r.stock_name || ''),
    code,
    desc: r.desc || '',
    ts,
    read: !!r.dismissed_at,
  }
}

/** 本地 item → POST payload。 */
function toPayload(n) {
  return {
    kind: n.kind || 'alert',
    tone: n.tone || null,
    stock_code: n.code || null,
    stock_name: n.stock && n.stock !== n.code ? n.stock : null,
    title: n.tag || '提醒',
    desc: n.desc || null,
  }
}

export const useNotificationsStore = defineStore('notifications', () => {
  // n = { id, serverId?, kind, tone, tag, stock, code, desc, ts, read }
  const items = ref(loadFromLS())

  watch(items, (v) => localStorage.setItem(LS_KEY, JSON.stringify(v)), { deep: true })

  const unreadCount = computed(() => items.value.filter((x) => !x.read).length)

  function push(n) {
    const it = {
      id: uid(),
      serverId: null,
      ts: Math.floor(Date.now() / 1000),
      read: false,
      kind: 'alert',
      tone: 'qwen',
      ...n,
    }
    items.value = normalizeItems([it, ...items.value])

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

    // 登录态下镜像到后端，失败静默
    if (isLoggedIn()) {
      notifApi.createNotification(toPayload(it))
        .then((row) => { it.serverId = row.id })
        .catch(() => {})
    }
  }

  function markRead(id) {
    const x = items.value.find((i) => i.id === id)
    if (!x || x.read) return
    x.read = true
    if (isLoggedIn() && x.serverId != null) {
      notifApi.markRead(x.serverId).catch(() => {})
    }
  }

  function markAllRead() {
    items.value.forEach((x) => (x.read = true))
    if (isLoggedIn()) {
      notifApi.markAllRead().catch(() => {})
    }
  }

  function clear() {
    items.value = []
    if (isLoggedIn()) {
      notifApi.clearNotifications().catch(() => {})
    }
  }

  /** 登录态：拉服务端通知列表，整段替换本地。 */
  async function syncFromServer() {
    if (!isLoggedIn()) return
    let remote
    try {
      remote = await notifApi.listNotifications(MAX)
    } catch {
      return
    }
    if (!Array.isArray(remote)) return
    items.value = normalizeItems(remote.map(fromServer))
  }

  async function ensurePermission() {
    if (typeof Notification === 'undefined') return 'unsupported'
    if (Notification.permission === 'granted') return 'granted'
    if (Notification.permission === 'denied') return 'denied'
    return await Notification.requestPermission()
  }

  return {
    items,
    unreadCount,
    push,
    markRead,
    markAllRead,
    clear,
    ensurePermission,
    syncFromServer,
  }
})
