// 千问对话历史。
// 每条 = 一次完整查询的快照：query + 解析条件 + 结果（前 N 只）+ 时间戳。
//
// 持久化策略：
//   - 始终写 localStorage（offline 兜底，跨刷新保留）
//   - 登录态下：syncFromServer 拉服务端历史替换本地；新加历史 POST 到后端
//     并把服务端返回的 id 写回本地 serverId 字段（用于后续 DELETE）
//   - 未登录：只用 localStorage，新加历史不打后端

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import * as chatApi from '../api/chat'

const LS_KEY = 'qwen.chat.history.v1'
const MAX_ITEMS = 50          // 最多 50 条
const MAX_RESULT_PRESERVE = 12  // 每条最多保留 12 只命中

let _seq = 0

function isLoggedIn() {
  return !!localStorage.getItem('token')
}

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

/** 服务端行 → 本地 item。serverId 字段用于后续 DELETE。 */
function fromServer(r) {
  const ts = r.created_at ? Math.floor(new Date(r.created_at).getTime() / 1000) : Math.floor(Date.now() / 1000)
  const meta = r.screen_meta || null
  return {
    id: uid(),
    serverId: r.id,
    ts,
    query: r.query || '',
    parsedConditions: r.parsed_conditions || [],
    items: (r.items || []).slice(0, MAX_RESULT_PRESERVE),
    total: r.total || 0,
    screenMeta: meta,
    agentAnswer: meta?.agent_answer || '',
    agentPlan: meta?.agent_plan || null,
    toolTrace: meta?.tool_trace || [],
  }
}

/** 本地 item → POST payload。 */
function toPayload(it) {
  const screenMeta = { ...(it.screenMeta || {}) }
  if (it.agentAnswer) screenMeta.agent_answer = it.agentAnswer
  if (it.agentPlan) screenMeta.agent_plan = it.agentPlan
  if (it.toolTrace?.length) screenMeta.tool_trace = it.toolTrace
  return {
    query: it.query,
    parsed_conditions: it.parsedConditions || [],
    items: it.items || [],
    total: it.total || 0,
    screen_meta: Object.keys(screenMeta).length ? screenMeta : null,
  }
}

export const useChatHistoryStore = defineStore('chatHistory', () => {
  const items = ref(loadFromLS())     // [{id, serverId?, query, parsedConditions, items, total, screenMeta, ts}]
  const activeId = ref(null)          // 当前展示的会话 id（null = 新会话）

  watch(items, (v) => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(v)) } catch { /* 配额满等情况静默 */ }
  }, { deep: true })

  function add(snapshot) {
    const it = {
      id: uid(),
      serverId: null,
      ts: Math.floor(Date.now() / 1000),
      query: String(snapshot.query || '').slice(0, 200),
      parsedConditions: snapshot.parsedConditions || [],
      items: (snapshot.items || []).slice(0, MAX_RESULT_PRESERVE),
      total: snapshot.total || 0,
      screenMeta: snapshot.screenMeta || null,
      agentAnswer: snapshot.agentAnswer || '',
      agentPlan: snapshot.agentPlan || null,
      toolTrace: snapshot.toolTrace || [],
    }
    items.value.unshift(it)
    if (items.value.length > MAX_ITEMS) items.value.length = MAX_ITEMS
    activeId.value = it.id

    if (isLoggedIn()) {
      chatApi.createSession(toPayload(it))
        .then((row) => { it.serverId = row.id })
        .catch(() => { /* offline 静默；下次 syncFromServer 时不会冒出来，无所谓 */ })
    }
    return it
  }

  function remove(id) {
    const it = items.value.find((x) => x.id === id)
    items.value = items.value.filter((x) => x.id !== id)
    if (activeId.value === id) activeId.value = null
    if (isLoggedIn() && it?.serverId != null) {
      chatApi.deleteSession(it.serverId).catch(() => {})
    }
  }

  function clear() {
    items.value = []
    activeId.value = null
    if (isLoggedIn()) {
      chatApi.clearSessions().catch(() => {})
    }
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

  /** 登录态下：拉服务端历史，整段替换本地（服务端是 source of truth）。 */
  async function syncFromServer() {
    if (!isLoggedIn()) return
    let remote
    try {
      remote = await chatApi.listSessions(MAX_ITEMS)
    } catch {
      return // 离线/未授权静默
    }
    if (!Array.isArray(remote)) return
    items.value = remote.map(fromServer)
    if (activeId.value && !items.value.find((x) => x.id === activeId.value)) {
      activeId.value = null
    }
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

  return { items, activeId, grouped, add, remove, clear, get, activate, newSession, syncFromServer }
})
