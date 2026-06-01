// 千问对话会话历史。
// 每条 session = 一段可恢复的多轮 thread；旧的单轮快照会自动转换为单 turn session。

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import * as chatApi from '../api/chat'

const LS_KEY = 'qwen.chat.history.v1'
const ACTIVE_KEY = 'qwen.chat.activeSession.v1'
const NEW_SESSION_ID = '__new__'
const MAX_SESSIONS = 50
const MAX_TURNS = 20
const MAX_RESULT_PRESERVE = 12

let _seq = 0

function isLoggedIn() {
  return !!localStorage.getItem('token')
}

function uid() {
  _seq += 1
  return `${Date.now().toString(36)}-${_seq}`
}

function safeTitle(text) {
  const title = String(text || '新建对话').replace(/\s+/g, ' ').trim() || '新建对话'
  return title.length > 24 ? `${title.slice(0, 24)}…` : title
}

function normalizeTurn(raw = {}) {
  const result = raw.result
    ? {
        ...raw.result,
        items: (raw.result.items || []).slice(0, MAX_RESULT_PRESERVE),
      }
    : raw.items || raw.total != null
      ? {
          items: (raw.items || []).slice(0, MAX_RESULT_PRESERVE),
          total: raw.total || 0,
          parsed_conditions: raw.parsedConditions || raw.parsed_conditions || [],
        }
      : null

  return {
    id: raw.id || uid(),
    ts: raw.ts || Math.floor(Date.now() / 1000),
    query: raw.query || '',
    phase: raw.phase || 'done',
    thinkingBuf: raw.thinkingBuf || '',
    parsedConditions: raw.parsedConditions || raw.parsed_conditions || result?.parsed_conditions || [],
    screenMeta: raw.screenMeta || raw.screen_meta || null,
    result,
    agentAnswer: raw.agentAnswer || raw.agent_answer || raw.screenMeta?.agent_answer || raw.screen_meta?.agent_answer || '',
    agentPlan: raw.agentPlan || raw.agent_plan || raw.screenMeta?.agent_plan || raw.screen_meta?.agent_plan || null,
    toolTrace: raw.toolTrace || raw.tool_trace || raw.screenMeta?.tool_trace || raw.screen_meta?.tool_trace || [],
    toolCalls: raw.toolCalls || raw.tool_calls || raw.screenMeta?.tool_calls || raw.screen_meta?.tool_calls || [],
    errorMsg: raw.errorMsg || '',
    tStart: raw.tStart || 0,
    tParsed: raw.tParsed || 0,
    tDone: raw.tDone || 0,
  }
}

function latestTurn(session) {
  return session?.turns?.[session.turns.length - 1] || null
}

function sessionStatus(session) {
  const turn = latestTurn(session)
  const tool = turn?.agentPlan?.tool
  if (tool === 'strategy_design') return '策略'
  if (tool === 'ask_clarification') return '追问'
  if (tool === 'explain_result') return '解释'
  if (turn?.result) return `${turn.result.total || 0}只`
  return `${session.turns?.length || 0}轮`
}

function applyLatestSnapshot(session) {
  const turn = latestTurn(session)
  session.query = session.turns?.[0]?.query || session.query || ''
  session.title = session.title || safeTitle(session.query)
  session.turnCount = session.turns?.length || 0
  session.status = sessionStatus(session)
  session.parsedConditions = turn?.parsedConditions || []
  session.items = (turn?.result?.items || []).slice(0, MAX_RESULT_PRESERVE)
  session.total = turn?.result?.total || 0
  session.screenMeta = turn?.screenMeta || null
  session.agentAnswer = turn?.agentAnswer || ''
  session.agentPlan = turn?.agentPlan || null
  session.toolTrace = turn?.toolTrace || []
  session.toolCalls = turn?.toolCalls || []
  return session
}

function legacySnapshotToTurn(raw = {}) {
  return normalizeTurn({
    query: raw.query,
    ts: raw.ts,
    parsedConditions: raw.parsedConditions || raw.parsed_conditions || [],
    items: raw.items || [],
    total: raw.total || 0,
    screenMeta: raw.screenMeta || raw.screen_meta || null,
    agentAnswer: raw.agentAnswer,
    agentPlan: raw.agentPlan,
    toolTrace: raw.toolTrace,
    toolCalls: raw.toolCalls,
  })
}

function normalizeSession(raw = {}) {
  const meta = raw.screenMeta || raw.screen_meta || {}
  const turns = Array.isArray(raw.turns)
    ? raw.turns
    : Array.isArray(meta?.thread)
      ? meta.thread
      : [legacySnapshotToTurn(raw)]

  const normalizedTurns = turns
    .filter((turn) => turn?.query || turn?.agentAnswer || turn?.result)
    .slice(-MAX_TURNS)
    .map(normalizeTurn)

  const firstTurn = normalizedTurns[0] || legacySnapshotToTurn(raw)
  const updatedAt = raw.updatedAt || meta?.session_updated_at || raw.ts || firstTurn.ts || Math.floor(Date.now() / 1000)
  const session = {
    id: raw.id || uid(),
    serverId: raw.serverId ?? raw.server_id ?? null,
    ts: raw.ts || firstTurn.ts || updatedAt,
    updatedAt,
    title: safeTitle(raw.title || meta?.session_title || firstTurn.query || raw.query),
    query: raw.query || firstTurn.query || '',
    turns: normalizedTurns.length ? normalizedTurns : [firstTurn],
  }
  return applyLatestSnapshot(session)
}

function loadFromLS() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr.map(normalizeSession).sort((a, b) => (b.updatedAt || b.ts) - (a.updatedAt || a.ts))
  } catch {
    return []
  }
}

function fromServer(row) {
  const meta = row.screen_meta || null
  return normalizeSession({
    id: meta?.session_client_id || `server-${row.id}`,
    serverId: row.id,
    ts: row.created_at ? Math.floor(new Date(row.created_at).getTime() / 1000) : Math.floor(Date.now() / 1000),
    query: row.query || '',
    parsed_conditions: row.parsed_conditions || [],
    items: row.items || [],
    total: row.total || 0,
    screen_meta: meta,
  })
}

function toPayload(session) {
  const turn = latestTurn(session)
  const meta = {
    ...(turn?.screenMeta || {}),
    agent_answer: turn?.agentAnswer || '',
    agent_plan: turn?.agentPlan || null,
    tool_trace: turn?.toolTrace || [],
    tool_calls: turn?.toolCalls || [],
    session_client_id: session.id,
    session_title: session.title,
    session_updated_at: session.updatedAt,
    session_status: session.status,
    thread: session.turns || [],
  }
  return {
    query: session.query || turn?.query || session.title,
    parsed_conditions: turn?.parsedConditions || [],
    items: (turn?.result?.items || []).slice(0, MAX_RESULT_PRESERVE),
    total: turn?.result?.total || 0,
    screen_meta: meta,
  }
}

export const useChatHistoryStore = defineStore('chatHistory', () => {
  const items = ref(loadFromLS())
  const storedActiveId = localStorage.getItem(ACTIVE_KEY)
  const activeId = ref(storedActiveId || items.value[0]?.id || null)
  const pendingCreates = new Set()

  watch(items, (value) => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(value)) } catch { /* ignore storage quota */ }
  }, { deep: true })

  watch(activeId, (value) => {
    try {
      if (value) localStorage.setItem(ACTIVE_KEY, value)
      else localStorage.removeItem(ACTIVE_KEY)
    } catch { /* ignore storage quota */ }
  })

  const activeSession = computed(() => {
    if (activeId.value === NEW_SESSION_ID) return null
    return items.value.find((item) => item.id === activeId.value) || null
  })

  function sortAndTrim() {
    items.value = [...items.value]
      .sort((a, b) => (b.updatedAt || b.ts) - (a.updatedAt || a.ts))
      .slice(0, MAX_SESSIONS)
  }

  function upsertLocal(session) {
    const normalized = applyLatestSnapshot(normalizeSession(session))
    const idx = items.value.findIndex((item) => item.id === normalized.id)
    if (idx >= 0) items.value.splice(idx, 1, normalized)
    else items.value.unshift(normalized)
    activeId.value = normalized.id
    sortAndTrim()
    return normalized
  }

  function persistRemote(session) {
    if (!isLoggedIn()) return
    const payload = toPayload(session)
    if (session.serverId != null) {
      chatApi.updateSession(session.serverId, payload).catch(() => {})
      return
    }
    if (pendingCreates.has(session.id)) return
    pendingCreates.add(session.id)
    chatApi.createSession(payload)
      .then((row) => {
        const current = items.value.find((item) => item.id === session.id)
        if (!current) return
        current.serverId = row.id
        return chatApi.updateSession(row.id, toPayload(current)).catch(() => {})
      })
      .catch(() => {})
      .finally(() => pendingCreates.delete(session.id))
  }

  function saveThread(turns) {
    const normalizedTurns = (turns || []).slice(-MAX_TURNS).map(normalizeTurn)
    if (!normalizedTurns.length) return null

    const existing = activeSession.value
    const session = upsertLocal({
      ...(existing || {}),
      id: existing?.id || uid(),
      serverId: existing?.serverId ?? null,
      ts: existing?.ts || normalizedTurns[0].ts || Math.floor(Date.now() / 1000),
      updatedAt: Math.floor(Date.now() / 1000),
      title: existing?.title || safeTitle(normalizedTurns[0].query),
      query: existing?.query || normalizedTurns[0].query || '',
      turns: normalizedTurns,
    })
    persistRemote(session)
    return session
  }

  function add(snapshot) {
    return saveThread([legacySnapshotToTurn(snapshot)])
  }

  function remove(id) {
    const session = items.value.find((item) => item.id === id)
    items.value = items.value.filter((item) => item.id !== id)
    if (activeId.value === id) activeId.value = null
    if (isLoggedIn() && session?.serverId != null) {
      chatApi.deleteSession(session.serverId).catch(() => {})
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
    return items.value.find((item) => item.id === id)
  }

  function activate(id) {
    activeId.value = id
  }

  function newSession() {
    activeId.value = NEW_SESSION_ID
  }

  async function syncFromServer() {
    if (!isLoggedIn()) return
    let remote
    try {
      remote = await chatApi.listSessions(MAX_SESSIONS)
    } catch {
      return
    }
    if (!Array.isArray(remote)) return

    const remoteSessions = remote.map(fromServer)
    const remoteIds = new Set(remoteSessions.map((item) => item.serverId).filter((id) => id != null))
    const localOnly = items.value.filter((item) => item.serverId == null || !remoteIds.has(item.serverId))
    items.value = [...remoteSessions, ...localOnly]
      .sort((a, b) => (b.updatedAt || b.ts) - (a.updatedAt || a.ts))
      .slice(0, MAX_SESSIONS)
    if (!activeId.value && items.value.length) {
      activeId.value = items.value[0].id
      return
    }
    if (activeId.value && !items.value.find((item) => item.id === activeId.value)) {
      activeId.value = items.value[0]?.id || null
    }
  }

  const grouped = computed(() => {
    const now = new Date()
    const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x.getTime() / 1000 }
    const today0 = startOfDay(now)
    const yest0 = today0 - 86400
    const dayOfWeek = now.getDay() === 0 ? 6 : now.getDay() - 1
    const week0 = today0 - dayOfWeek * 86400

    const buckets = { today: [], yesterday: [], thisWeek: [], earlier: [] }
    for (const session of items.value) {
      const ts = session.updatedAt || session.ts
      if (ts >= today0) buckets.today.push(session)
      else if (ts >= yest0) buckets.yesterday.push(session)
      else if (ts >= week0) buckets.thisWeek.push(session)
      else buckets.earlier.push(session)
    }
    return buckets
  })

  return {
    items,
    activeId,
    activeSession,
    grouped,
    add,
    saveThread,
    remove,
    clear,
    get,
    activate,
    newSession,
    syncFromServer,
  }
})
