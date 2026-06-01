import { computed, ref } from 'vue'
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
    screenMeta: raw.screenMeta || null,
    result: raw.result || null,
    agentAnswer: raw.agentAnswer || '',
    agentPlan: raw.agentPlan || null,
    toolTrace: raw.toolTrace || [],
    errorMsg: raw.errorMsg || '',
    tStart: raw.tStart || 0,
    tParsed: raw.tParsed || 0,
    tDone: raw.tDone || 0,
  }
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

function persistCurrentThread(turns) {
  const payload = JSON.stringify(turns.slice(-MAX_THREAD_TURNS))
  try { sessionStorage.setItem(CURRENT_THREAD_KEY, payload) } catch { /* ignore storage quota */ }
  try { localStorage.setItem(CURRENT_THREAD_KEY, payload) } catch { /* ignore storage quota */ }
}

function turnToContext(turn) {
  if (!turn) return null
  return {
    last_query: turn.query || '',
    last_plan: turn.agentPlan || null,
    last_answer: turn.agentAnswer || '',
    last_conditions: turn.parsedConditions || [],
    last_result: turn.result
      ? {
          total: turn.result.total || 0,
          items: (turn.result.items || []).slice(0, 8),
          parsed_conditions: turn.result.parsed_conditions || turn.parsedConditions || [],
        }
      : null,
  }
}

/**
 * NL 筛选 SSE 状态机：把 Chat.vue 的流式逻辑抽出来，便于测试和复用。
 *
 * 状态：idle → thinking → parsed → screening → done | error
 * @param {{add: function, get: function}} historyStore  pinia chatHistory store
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
  const errorMsg = ref('')
  const thread = ref(loadCurrentThread())

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
    errorMsg.value = t.errorMsg || ''
    tStart.value = t.tStart || (t.ts ? t.ts * 1000 : 0)
    tParsed.value = t.tParsed || tStart.value
    tDone.value = t.tDone || tParsed.value
    if (result.value?.items?.length && hooks.onResult) {
      hooks.onResult(result.value.items.map((s) => s.code))
    }
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

  function buildContext() {
    return turnToContext(latestContextTurn()) || {
      last_query: '',
      last_plan: null,
      last_answer: '',
      last_conditions: [],
      last_result: null,
    }
  }

  function commitCurrentTurn() {
    const turn = snapshotCurrentTurn('done')
    if (!turn.query) return null
    thread.value = [...thread.value, turn].slice(-MAX_THREAD_TURNS)
    persistCurrentThread(thread.value)
    return turn
  }

  function clearThread() {
    thread.value = []
    persistCurrentThread(thread.value)
    reset()
  }

  function applyAgentMeta(ev) {
    parsedConditions.value = ev.conditions || ev.plan?.conditions || parsedConditions.value || []
    agentAnswer.value = ev.answer || ''
    agentPlan.value = ev.plan || null
    toolTrace.value = ev.tool_trace || []
    screenMeta.value = {
      mode: ev.plan?.tool || 'agent',
      tool: ev.plan?.tool || 'agent',
      tool_label: ev.plan?.tool_label || 'Agent',
      agent_plan: ev.plan || null,
      agent_answer: ev.answer || '',
      tool_trace: ev.tool_trace || [],
      warnings: ev.warnings || [],
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
        } else if (ev.type === 'parsed') {
          applyAgentMeta(ev)
          parsedConditions.value = ev.conditions || []
          screenMeta.value = {
            ...(screenMeta.value || {}),
            logic: ev.logic,
            sort_by: ev.sort_by,
            sort_desc: ev.sort_desc,
            limit: ev.limit,
          }
          phase.value = 'parsed'
          tParsed.value = Date.now()
        } else if (ev.type === 'planned') {
          applyAgentMeta(ev)
          phase.value = 'parsed'
          tParsed.value = Date.now()
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
              parsed_conditions: ev.result.parsed_conditions || parsedConditions.value,
              strategy: ev.result.strategy || null,
            }
            if (hooks.onResult) hooks.onResult((ev.result.items || []).map((s) => s.code))
          }
          phase.value = 'done'
          tParsed.value = Date.now()
          tDone.value = Date.now()
        } else if (ev.type === 'screening') {
          screenMeta.value = {
            ...(screenMeta.value || {}),
            tool: ev.tool || screenMeta.value?.tool || 'stock_screen',
            tool_label: ev.tool_label || screenMeta.value?.tool_label || '股票筛选',
          }
          phase.value = 'screening'
        } else if (ev.type === 'result') {
          applyAgentMeta(ev)
          result.value = {
            items: ev.items || [],
            total: ev.total || 0,
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

      if (phase.value === 'done') {
        const turn = commitCurrentTurn()
        historyStore.add({
          query: q,
          parsedConditions: parsedConditions.value,
          items: result.value?.items || [],
          total: result.value?.total || 0,
          screenMeta: screenMeta.value,
          agentAnswer: agentAnswer.value,
          agentPlan: agentPlan.value,
          toolTrace: toolTrace.value,
          threadTurnId: turn?.id,
        })
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        phase.value = 'idle'
      } else {
        errorMsg.value = friendlyError(e, { context: 'ai' })
        phase.value = 'error'
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
    reset()
    lastQuery.value = it.query
    parsedConditions.value = it.parsedConditions || []
    screenMeta.value = it.screenMeta || null
    agentAnswer.value = it.agentAnswer || it.screenMeta?.agent_answer || ''
    agentPlan.value = it.agentPlan || it.screenMeta?.agent_plan || null
    toolTrace.value = it.toolTrace || it.screenMeta?.tool_trace || []
    if (['strategy_design', 'ask_clarification', 'explain_result'].includes(agentPlan.value?.tool)) {
      result.value = null
    } else {
      result.value = {
        items: it.items || [],
        total: it.total || 0,
        parsed_conditions: it.parsedConditions || [],
      }
      if (hooks.onResult) hooks.onResult((it.items || []).map((s) => s.code))
    }
    phase.value = 'done'
    tStart.value = it.ts * 1000
    tDone.value = it.ts * 1000
    thread.value = [snapshotCurrentTurn('done')]
    persistCurrentThread(thread.value)
    return true
  }

  restoreLatestThreadState()

  return {
    // state
    phase, lastQuery, thinkingBuf, parsedConditions, screenMeta, result, agentAnswer, agentPlan, toolTrace, errorMsg,
    thread, liveTurn,
    tStart, tParsed, tDone,
    isStreaming,
    // actions
    reset, send, stop, restoreFromHistory, clearThread,
  }
}
