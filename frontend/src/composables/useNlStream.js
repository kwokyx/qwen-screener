import { computed, ref, watch } from 'vue'
import { streamNL } from '../api/screener'
import { friendlyError } from '../shared/errors.js'

const CURRENT_THREAD_KEY = 'qwen.chat.currentThread.v1'
const MAX_THREAD_TURNS = 20

let turnSeq = 0

function makeTurnId() {
  turnSeq += 1
  return `${Date.now().toString(36)}-${turnSeq}`
}

function cloneJson(value, fallback = null) {
  try {
    return value == null ? fallback : JSON.parse(JSON.stringify(value))
  } catch {
    return fallback
  }
}

function normalizeTurn(raw = {}) {
  return {
    id: raw.id || makeTurnId(),
    ts: raw.ts || Math.floor(Date.now() / 1000),
    query: raw.query || '',
    phase: raw.phase || 'done',
    thinkingBuf: raw.thinkingBuf || '',
    parsedConditions: raw.parsedConditions || [],
    screenMeta: raw.screenMeta || (raw.aiStatus || raw.ai_status ? { ai_status: raw.aiStatus || raw.ai_status } : null),
    result: raw.result || null,
    agentAnswer: raw.agentAnswer || '',
    agentPlan: raw.agentPlan || null,
    toolTrace: raw.toolTrace || [],
    toolCalls: raw.toolCalls || raw.tool_calls || [],
    reactSteps: raw.reactSteps || raw.react_steps || [],
    aiStatus: raw.aiStatus || raw.ai_status || null,
    errorMsg: raw.errorMsg || '',
    tStart: raw.tStart || 0,
    tParsed: raw.tParsed || 0,
    tDone: raw.tDone || 0,
  }
}

function extractTimingMeta(ev = {}, previousMeta = {}) {
  const source = ev.timings || {}
  const hasTiming = (
    ev.planning_ms != null ||
    ev.model_ms != null ||
    ev.tool_ms != null ||
    ev.fallback_reason != null ||
    source.planning_ms != null ||
    source.model_ms != null ||
    source.tool_ms != null ||
    source.fallback_reason != null
  )
  if (!hasTiming) return {}
  const previous = previousMeta.timings || {}
  const timings = {
    planning_ms: ev.planning_ms ?? source.planning_ms ?? previous.planning_ms ?? previousMeta.planning_ms ?? 0,
    model_ms: ev.model_ms ?? source.model_ms ?? previous.model_ms ?? previousMeta.model_ms ?? 0,
    tool_ms: ev.tool_ms ?? source.tool_ms ?? previous.tool_ms ?? previousMeta.tool_ms ?? 0,
    fallback_reason: ev.fallback_reason ?? source.fallback_reason ?? previous.fallback_reason ?? previousMeta.fallback_reason ?? null,
  }
  return {
    timings,
    planning_ms: timings.planning_ms,
    model_ms: timings.model_ms,
    tool_ms: timings.tool_ms,
    fallback_reason: timings.fallback_reason,
  }
}

function reactEventText(ev = {}) {
  const toolLabel = {
    stock_screen: '股票筛选',
    strategy_select: '策略选股',
    strategy_design: '策略设计',
    explain_result: '结果解释',
    sort_results: '结果排序',
    paginate_results: '结果分页',
    stock_detail: '个股详情',
    ask_clarification: '补充追问',
  }[ev.tool] || ev.tool || 'Agent'
  if (ev.type === 'react_step') return `模型选择下一步：${toolLabel}`
  if (ev.type === 'tool_start') return `正在调用工具：${toolLabel}`
  if (ev.type === 'tool_observation') return `已获得观察结果：${ev.public_summary || toolLabel}`
  if (ev.type === 'tool_done') return `工具完成：${toolLabel}`
  if (ev.type === 'final') return ev.public_summary || '已生成最终回答'
  return ev.public_summary || ''
}

function loadCurrentThread() {
  try {
    const raw = sessionStorage.getItem(CURRENT_THREAD_KEY) || localStorage.getItem(CURRENT_THREAD_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.slice(-MAX_THREAD_TURNS).map(normalizeTurn)
  } catch {
    return []
  }
}

function loadSessionThread(historyStore) {
  const session = historyStore?.activeSession
  if (!session?.turns?.length) return []
  return session.turns.slice(-MAX_THREAD_TURNS).map(normalizeTurn)
}

function loadInitialThread(historyStore) {
  const sessionThread = loadSessionThread(historyStore)
  return sessionThread.length ? sessionThread : loadCurrentThread()
}

function persistCurrentThread(turns) {
  const payload = JSON.stringify(turns.slice(-MAX_THREAD_TURNS))
  try { sessionStorage.setItem(CURRENT_THREAD_KEY, payload) } catch { /* ignore storage quota */ }
  try { localStorage.setItem(CURRENT_THREAD_KEY, payload) } catch { /* ignore storage quota */ }
}

function summarizeTurn(turn) {
  if (!turn) return null
  return {
    query: (turn.query || '').slice(0, 180),
    tool: turn.agentPlan?.tool || null,
    answer: (turn.agentAnswer || '').slice(0, 240),
    conditions: (turn.parsedConditions || []).slice(0, 8),
    result: turn.result
      ? {
          total: turn.result.total || 0,
          items: (turn.result.items || []).slice(0, 3).map((item) => ({
            code: item.code,
            name: item.name,
          })),
        }
      : null,
  }
}

function turnToContext(turn, recentTurns = [], sessionId = null) {
  if (!turn) return null
  return {
    session_id: sessionId,
    turn_id: turn.id || null,
    last_query: turn.query || '',
    last_plan: turn.agentPlan || null,
    last_answer: turn.agentAnswer || '',
    last_conditions: turn.parsedConditions || [],
    last_screen_meta: turn.screenMeta || null,
    last_tool_trace: turn.toolTrace || [],
    last_tool_calls: turn.toolCalls || [],
    last_result: turn.result
      ? {
          total: turn.result.total || 0,
          offset: turn.result.offset || 0,
          limit: turn.result.limit || 50,
          trade_date: turn.result.trade_date || null,
          items: (turn.result.items || []).slice(0, 8),
          parsed_conditions: turn.result.parsed_conditions || turn.parsedConditions || [],
        }
      : null,
    recent_turns: recentTurns.slice(-6).map(summarizeTurn).filter(Boolean),
  }
}

/**
 * NL 筛选 SSE 状态机：把 Chat.vue 的流式逻辑抽出来，便于测试和复用。
 *
 * 状态：idle → thinking → parsed → screening → done | error
 * @param {{saveThread: function, get: function, activate: function, activeSession: object}} historyStore  pinia chatHistory store
 * @param {{onResult?: (codes: string[]) => void}} hooks  事件钩子（如懒加载 sparkline）
 */
export function useNlStream(historyStore, hooks = {}) {
  // ---- 状态 ----
  const phase = ref('idle')
  const lastQuery = ref('')
  const thinkingBuf = ref('')
  const parsedConditions = ref([])
  const screenMeta = ref(null)
  const result = ref(null)
  const agentAnswer = ref('')
  const agentPlan = ref(null)
  const toolTrace = ref([])
  const toolCalls = ref([])
  const reactSteps = ref([])
  const errorMsg = ref('')
  const thread = ref(loadInitialThread(historyStore))

  // 各阶段时间戳，inspector 显示用时
  const tStart = ref(0)
  const tParsed = ref(0)
  const tDone = ref(0)

  let abortCtrl = null

  const isStreaming = computed(() =>
    phase.value === 'thinking' || phase.value === 'parsed' || phase.value === 'screening'
  )

  const liveTurn = computed(() => {
    if (!lastQuery.value) return null
    return snapshotCurrentTurn(phase.value)
  })

  // ---- 控制函数 ----

  function reset() {
    phase.value = 'idle'
    thinkingBuf.value = ''
    parsedConditions.value = []
    screenMeta.value = null
    result.value = null
    agentAnswer.value = ''
    agentPlan.value = null
    toolTrace.value = []
    toolCalls.value = []
    reactSteps.value = []
    errorMsg.value = ''
  }

  function restoreLatestThreadState() {
    const latest = thread.value[thread.value.length - 1]
    if (!latest) return
    applyTurnToCurrent(latest)
  }

  function applyTurnToCurrent(turn) {
    const t = normalizeTurn(turn)
    phase.value = t.phase || 'done'
    lastQuery.value = t.query || ''
    thinkingBuf.value = t.thinkingBuf || ''
    parsedConditions.value = t.parsedConditions || []
    screenMeta.value = t.screenMeta || null
    result.value = t.result || null
    agentAnswer.value = t.agentAnswer || ''
    agentPlan.value = t.agentPlan || null
    toolTrace.value = t.toolTrace || []
    toolCalls.value = t.toolCalls || []
    reactSteps.value = t.reactSteps || []
    errorMsg.value = t.errorMsg || ''
    tStart.value = t.tStart || (t.ts ? t.ts * 1000 : 0)
    tParsed.value = t.tParsed || tStart.value
    tDone.value = t.tDone || tParsed.value
    if (result.value?.items?.length && hooks.onResult) {
      hooks.onResult(result.value.items.map((s) => s.code))
    }
  }

  function restoreSession(session) {
    if (!session?.turns?.length) return false
    const turns = session.turns.slice(-MAX_THREAD_TURNS).map(normalizeTurn)
    if (!turns.length) return false
    reset()
    thread.value = turns
    persistCurrentThread(thread.value)
    applyTurnToCurrent(turns[turns.length - 1])
    if (hooks.onResult) {
      const codes = [...new Set(turns.flatMap((turn) => (turn.result?.items || []).map((s) => s.code)))]
      if (codes.length) hooks.onResult(codes)
    }
    return true
  }

  function snapshotCurrentTurn(turnPhase = phase.value) {
    return normalizeTurn({
      query: lastQuery.value,
      phase: turnPhase,
      thinkingBuf: thinkingBuf.value,
      parsedConditions: cloneJson(parsedConditions.value, []),
      screenMeta: cloneJson(screenMeta.value, null),
      result: cloneJson(result.value, null),
      agentAnswer: agentAnswer.value,
      agentPlan: cloneJson(agentPlan.value, null),
      toolTrace: cloneJson(toolTrace.value, []),
      toolCalls: cloneJson(toolCalls.value, []),
      reactSteps: cloneJson(reactSteps.value, []),
      aiStatus: cloneJson(screenMeta.value?.ai_status, null),
      errorMsg: errorMsg.value,
      tStart: tStart.value,
      tParsed: tParsed.value,
      tDone: tDone.value,
    })
  }

  function latestContextTurn() {
    for (let i = thread.value.length - 1; i >= 0; i--) {
      const turn = thread.value[i]
      if (turn.agentPlan || turn.parsedConditions?.length || turn.result) return turn
    }
    return lastQuery.value ? snapshotCurrentTurn() : null
  }

  function latestResultTurn() {
    for (let i = thread.value.length - 1; i >= 0; i--) {
      const turn = thread.value[i]
      if (turn.result) return turn
    }
    return result.value ? snapshotCurrentTurn() : null
  }

  function buildContext() {
    const sessionId = historyStore?.activeId && historyStore.activeId !== '__new__'
      ? historyStore.activeId
      : null
    const context = turnToContext(latestContextTurn(), thread.value, sessionId) || {
      session_id: sessionId,
      last_query: '',
      last_plan: null,
      last_answer: '',
      last_conditions: [],
      last_result: null,
      recent_turns: [],
    }
    const resultContext = turnToContext(latestResultTurn(), [], sessionId)
    if (resultContext?.last_result && !context.last_result) {
      context.last_result = resultContext.last_result
    }
    if (resultContext?.last_conditions?.length && !context.last_conditions?.length) {
      context.last_conditions = resultContext.last_conditions
    }
    if (resultContext?.last_screen_meta && !context.last_screen_meta) {
      context.last_screen_meta = resultContext.last_screen_meta
    }
    return context
  }

  function commitCurrentTurn(turnPhase = 'done') {
    const turn = snapshotCurrentTurn(turnPhase)
    if (!turn.query) return null
    thread.value = [...thread.value, turn].slice(-MAX_THREAD_TURNS)
    persistCurrentThread(thread.value)
    historyStore.saveThread?.(thread.value)
    return turn
  }

  function clearThread() {
    thread.value = []
    persistCurrentThread(thread.value)
    reset()
    historyStore.newSession?.()
  }

  function applyAgentMeta(ev) {
    const previousMeta = screenMeta.value || {}
    parsedConditions.value = ev.conditions || ev.plan?.conditions || parsedConditions.value || []
    agentAnswer.value = ev.answer || ''
    agentPlan.value = ev.plan || null
    toolTrace.value = ev.tool_trace || []
    if (Array.isArray(ev.tool_calls)) {
      ev.tool_calls.forEach(mergeToolCall)
    }
    if (Array.isArray(ev.react_steps)) {
      reactSteps.value = cloneJson(ev.react_steps, [])
    }
    screenMeta.value = {
      ...previousMeta,
      ...extractTimingMeta(ev, previousMeta),
      mode: ev.plan?.tool || 'agent',
      tool: ev.plan?.tool || 'agent',
      tool_label: ev.plan?.tool_label || 'Agent',
      agent_plan: ev.plan || null,
      agent_answer: ev.answer || '',
      tool_trace: ev.tool_trace || [],
      tool_calls: cloneJson(toolCalls.value, []),
      react_steps: cloneJson(reactSteps.value, []),
      ai_status: ev.ai_status || previousMeta.ai_status || null,
      sort_by: ev.sort_by ?? ev.plan?.sort_by ?? previousMeta.sort_by,
      sort_desc: ev.sort_desc ?? ev.plan?.sort_desc ?? previousMeta.sort_desc,
      limit: ev.limit ?? previousMeta.limit,
      offset: ev.offset ?? ev.plan?.offset ?? previousMeta.offset,
      warnings: ev.warnings || [],
    }
  }

  function normalizeToolCall(call = {}) {
    const name = call.name || call.id || 'tool'
    return {
      id: call.id || name,
      name,
      label: call.label || name,
      status: call.status || 'done',
      params: call.params || {},
      result: call.result || {},
      message: call.message || '',
    }
  }

  function mergeToolCall(call) {
    const normalized = normalizeToolCall(call)
    const idx = toolCalls.value.findIndex((item) =>
      item.id === normalized.id || item.name === normalized.name
    )
    if (idx >= 0) {
      const next = [...toolCalls.value]
      next.splice(idx, 1, { ...next[idx], ...normalized })
      toolCalls.value = next
    } else {
      toolCalls.value = [...toolCalls.value, normalized]
    }
  }

  async function send(query) {
    const q = (query || '').trim()
    if (!q || isStreaming.value) return

    const context = buildContext()
    reset()
    lastQuery.value = q
    phase.value = 'thinking'
    tStart.value = Date.now()
    tParsed.value = 0
    tDone.value = 0
    abortCtrl = new AbortController()

    try {
      await streamNL(q, (ev) => {
        if (ev.type === 'thinking') {
          thinkingBuf.value += ev.text
        } else if (['react_step', 'tool_start', 'tool_observation', 'tool_done', 'final'].includes(ev.type)) {
          reactSteps.value = [...reactSteps.value, cloneJson(ev, {})]
          const text = reactEventText(ev)
          if (text) thinkingBuf.value += `${text}\n`
        } else if (ev.type === 'tool_call') {
          mergeToolCall(ev.tool_call)
        } else if (ev.type === 'parsed') {
          applyAgentMeta(ev)
          parsedConditions.value = ev.conditions || []
          screenMeta.value = {
            ...(screenMeta.value || {}),
            logic: ev.logic,
            sort_by: ev.sort_by,
            sort_desc: ev.sort_desc,
            limit: ev.limit,
            offset: ev.offset,
          }
          phase.value = 'parsed'
          tParsed.value = Date.now()
        } else if (ev.type === 'planned') {
          applyAgentMeta(ev)
          phase.value = 'parsed'
          tParsed.value = Date.now()
        } else if (ev.type === 'planning') {
          applyAgentMeta(ev)
        } else if (ev.type === 'design') {
          applyAgentMeta(ev)
          phase.value = 'done'
          tParsed.value = Date.now()
          tDone.value = Date.now()
        } else if (ev.type === 'agent') {
          applyAgentMeta(ev)
          if (ev.result) {
            result.value = {
              items: ev.result.items || [],
              total: ev.result.total || 0,
              offset: ev.result.offset || 0,
              limit: ev.result.limit || 50,
              trade_date: ev.result.trade_date || null,
              parsed_conditions: ev.result.parsed_conditions || parsedConditions.value,
              strategy: ev.result.strategy || null,
            }
            if (hooks.onResult) hooks.onResult((ev.result.items || []).map((s) => s.code))
          }
          phase.value = 'done'
          tParsed.value = Date.now()
          tDone.value = Date.now()
        } else if (ev.type === 'screening') {
          if (ev.tool_call) mergeToolCall(ev.tool_call)
          screenMeta.value = {
            ...(screenMeta.value || {}),
            ...extractTimingMeta(ev, screenMeta.value || {}),
            tool: ev.tool || screenMeta.value?.tool || 'stock_screen',
            tool_label: ev.tool_label || screenMeta.value?.tool_label || '股票筛选',
            tool_calls: cloneJson(toolCalls.value, []),
          }
          phase.value = 'screening'
        } else if (ev.type === 'result') {
          applyAgentMeta(ev)
          result.value = {
            items: ev.items || [],
            total: ev.total || 0,
            offset: ev.offset || 0,
            limit: ev.limit || 50,
            trade_date: ev.trade_date || null,
            parsed_conditions: ev.parsed_conditions || parsedConditions.value,
          }
          if (hooks.onResult) hooks.onResult((ev.items || []).map((s) => s.code))
        } else if (ev.type === 'done') {
          phase.value = 'done'
          tDone.value = Date.now()
        } else if (ev.type === 'error') {
          errorMsg.value = friendlyError(ev.message, { context: 'ai' })
          phase.value = 'error'
        }
      }, abortCtrl.signal, context)

      // 流正常结束但没收到 'done'
      if (phase.value !== 'error' && phase.value !== 'done') {
        phase.value = 'done'
        tDone.value = Date.now()
      }

      if (phase.value === 'done') commitCurrentTurn()
      else if (phase.value === 'error') commitCurrentTurn('error')
    } catch (e) {
      if (e.name === 'AbortError') {
        phase.value = 'idle'
      } else {
        errorMsg.value = friendlyError(e, { context: 'ai' })
        phase.value = 'error'
        commitCurrentTurn('error')
      }
    } finally {
      abortCtrl = null
    }
  }

  function stop() {
    abortCtrl?.abort()
  }

  // 点历史 → 还原整个会话（不重新调 AI）
  function restoreFromHistory(id) {
    if (isStreaming.value) return false
    const it = historyStore.get(id)
    if (!it) return false
    const ok = restoreSession(it)
    if (ok) historyStore.activate?.(id)
    return ok
  }

  restoreLatestThreadState()

  watch(
    () => historyStore.activeId,
    (id) => {
      if (!id || isStreaming.value || thread.value.length || lastQuery.value) return
      const session = historyStore.get?.(id)
      if (session) restoreSession(session)
    },
    { flush: 'post' }
  )

  return {
    // state
    phase, lastQuery, thinkingBuf, parsedConditions, screenMeta, result, agentAnswer, agentPlan, toolTrace, toolCalls, reactSteps, errorMsg,
    thread, liveTurn,
    tStart, tParsed, tDone,
    isStreaming,
    // actions
    reset, send, stop, restoreFromHistory, clearThread,
  }
}
