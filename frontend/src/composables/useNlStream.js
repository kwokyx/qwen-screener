import { computed, ref } from 'vue'
import { streamNL } from '../api/screener'
import { friendlyError } from '../shared/errors.js'

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

  // 各阶段时间戳，inspector 显示用时
  const tStart = ref(0)
  const tParsed = ref(0)
  const tDone = ref(0)

  let abortCtrl = null

  const isStreaming = computed(() =>
    phase.value === 'thinking' || phase.value === 'parsed' || phase.value === 'screening'
  )

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

  function buildContext() {
    return {
      last_query: lastQuery.value || '',
      last_plan: agentPlan.value || null,
      last_answer: agentAnswer.value || '',
      last_conditions: parsedConditions.value || [],
      last_result: result.value
        ? {
            total: result.value.total || 0,
            items: (result.value.items || []).slice(0, 8),
            parsed_conditions: result.value.parsed_conditions || parsedConditions.value || [],
          }
        : null,
    }
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
        historyStore.add({
          query: q,
          parsedConditions: parsedConditions.value,
          items: result.value?.items || [],
          total: result.value?.total || 0,
          screenMeta: screenMeta.value,
          agentAnswer: agentAnswer.value,
          agentPlan: agentPlan.value,
          toolTrace: toolTrace.value,
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
    return true
  }

  return {
    // state
    phase, lastQuery, thinkingBuf, parsedConditions, screenMeta, result, agentAnswer, agentPlan, toolTrace, errorMsg,
    tStart, tParsed, tDone,
    isStreaming,
    // actions
    reset, send, stop, restoreFromHistory,
  }
}
