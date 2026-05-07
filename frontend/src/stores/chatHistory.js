// 千问对话历史。
// 每条 = 一次完整查询的快照：query + 解析条件 + 结果（前 N 只）+ 时间戳。
// 写入 localStorage 跨刷新保留；点击可一键还原整个会话视图（不重新调用 AI）。

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

const LS_KEY = 'qwen.chat.history.v1'
const MAX_ITEMS = 50          // 最多 50 条
const MAX_RESULT_PRESERVE = 12  // 每条最多保留 12 只命中

let _seq = 0

function loadFromLS() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr
  } catch {
    return []
  }
}

function uid() {
  _seq++
  return `${Date.now().toString(36)}-${_seq}`
}

export const useChatHistoryStore = defineStore('chatHistory', () => {
  const items = ref(loadFromLS())     // [{id, query, parsedConditions, items, total, screenMeta, ts}]
  const activeId = ref(null)          // 当前展示的会话 id（null = 新会话）

  watch(items, (v) => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(v)) } catch { /* 配额满等情况静默 */ }
  }, { deep: true })

  function add(snapshot) {
    const it = {
      id: uid(),
      ts: Math.floor(Date.now() / 1000),
      query: String(snapshot.query || '').slice(0, 200),
      parsedConditions: snapshot.parsedConditions || [],
      items: (snapshot.items || []).slice(0, MAX_RESULT_PRESERVE),
      total: snapshot.total || 0,
      screenMeta: snapshot.screenMeta || null,
    }
    items.value.unshift(it)
    if (items.value.length > MAX_ITEMS) items.value.length = MAX_ITEMS
    activeId.value = it.id
    return it
  }

  function remove(id) {
    items.value = items.value.filter((x) => x.id !== id)
    if (activeId.value === id) activeId.value = null
  }

  function clear() {
    items.value = []
    activeId.value = null
  }

  function get(id) {
    return items.value.find((x) => x.id === id)
  }

  function activate(id) {
    activeId.value = id
  }

  function newSession() {
    activeId.value = null
  }

  // 按 (今天 / 昨天 / 本周内 / 更早) 分组
  const grouped = computed(() => {
    const now = new Date()
    const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x.getTime() / 1000 }
    const today0 = startOfDay(now)
    const yest0 = today0 - 86400
    const dayOfWeek = now.getDay() === 0 ? 6 : now.getDay() - 1   // 周一作为 0
    const week0 = today0 - dayOfWeek * 86400

    const buckets = { today: [], yesterday: [], thisWeek: [], earlier: [] }
    for (const it of items.value) {
      if (it.ts >= today0) buckets.today.push(it)
      else if (it.ts >= yest0) buckets.yesterday.push(it)
      else if (it.ts >= week0) buckets.thisWeek.push(it)
      else buckets.earlier.push(it)
    }
    return buckets
  })

  return { items, activeId, grouped, add, remove, clear, get, activate, newSession }
})
