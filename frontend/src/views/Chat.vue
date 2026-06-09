<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import EmptyState from '../components/EmptyState.vue'
import AiMarkdown from '../components/AiMarkdown.vue'
import { A2 } from '../shared/theme.js'
import { screen } from '../api/screener'
import { selectStrategy } from '../api/strategy'
import { useKlineCache } from '../composables/useKlineCache.js'
import { useNlStream } from '../composables/useNlStream.js'
import { useAiStatusStore } from '../stores/aiStatus'
import { useChatHistoryStore } from '../stores/chatHistory'

const aiStatus = useAiStatusStore()
const history = useChatHistoryStore()
const AGENT_RESULTS_KEY = 'qwen.results.agent.v1'

const router = useRouter()
const route = useRoute()

const input = ref('')

// 真实 sparkline 缓存（result 到达 / 历史恢复时调用 loadSparks）
const { load: loadSparks, get: spark } = useKlineCache(30)

// SSE 状态机：把流式逻辑都委托给 composable
const stream = useNlStream(history, {
  onResult: loadSparks,
  startFresh: Boolean(route.query.fresh),
})
const {
  phase, lastQuery, thinkingBuf, parsedConditions, screenMeta, result, agentAnswer, agentPlan, toolTrace, toolCalls, errorMsg,
  thread, liveTurn,
  tStart, tParsed, tDone, isStreaming,
  send: streamSend, stop, restoreFromHistory: streamRestore, clearThread,
} = stream

const chatScroll = ref(null)
const canSubmit = computed(() => Boolean(input.value.trim()) && !isStreaming.value)

const presetPrompts = [
  '帮我找近期强势突破的股票',
  '低估值高分红的银行股',
  '帮我找RPS强势突破的股票',
  '半导体行业市值 500 亿以上的龙头',
]

const fieldLabel = {
  pe: 'PE',
  pb: 'PB',
  roe: 'ROE',
  market_cap: '市值',
  dividend_yield: '股息率',
  revenue_yoy: '营收同比',
  profit_yoy: '净利润同比',
  gross_margin: '毛利率',
  debt_ratio: '资产负债率',
  industry: '行业',
  market: '板块',
  close: '现价',
  turnover: '换手率',
  ma5: 'MA5',
  ma20: 'MA20',
  volume_ratio_20: '20日放量倍数',
  breakout_20: '20日新高突破',
  ma5_above_ma20: 'MA5高于MA20',
  pct_change_20: '20日涨跌幅',
}
const opLabel = { gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', between: '∈', in: '∈' }
function fmtCond(c) {
  const field = fieldLabel[c.field] || c.field
  if (Array.isArray(c.value)) return `${field} ${opLabel[c.op] || c.op} ${c.value.join('、')}`
  return `${field} ${opLabel[c.op] || c.op} ${c.value}`
}

const conversationTurns = computed(() => {
  const turns = [...thread.value]
  const live = liveTurn.value
  if (live && (isStreaming.value || phase.value === 'error')) {
    return [...turns, live]
  }
  return turns
})
const hasConversation = computed(() => conversationTurns.value.length > 0)
const latestTurn = computed(() => conversationTurns.value[conversationTurns.value.length - 1] || liveTurn.value || null)
const resultPreviewItems = computed(() => (latestTurn.value?.result?.items || result.value?.items || []).slice(0, 6))
const fmtMetric = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d)
const fmtChange = (v) => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
function resultFacts(s) {
  if (s.signals?.length) return s.signals.slice(0, 2)
  return [
    s.pe != null ? `PE ${fmtMetric(s.pe)}` : null,
    s.roe != null ? `ROE ${fmtMetric(s.roe)}%` : null,
    s.dividend_yield != null ? `股息 ${fmtMetric(s.dividend_yield)}%` : null,
  ].filter(Boolean)
}

const fullResultsOpen = ref(false)
const fullResultsLoading = ref(false)
const fullResultsError = ref('')
const fullResultsTurn = ref(null)
const fullResultsMode = ref('screen')
const fullResultsItems = ref([])
const fullResultsTotal = ref(0)
const fullResultsPage = ref(1)
const fullResultsPageSize = ref(50)
const fullResultsTradeDate = ref(null)

const fullResultsEffectiveTotal = computed(() => (
  fullResultsMode.value === 'strategy'
    ? fullResultsItems.value.length
    : fullResultsTotal.value
))
const fullResultsPageCount = computed(() => Math.max(1, Math.ceil((fullResultsEffectiveTotal.value || 0) / fullResultsPageSize.value)))
const fullResultsStart = computed(() => fullResultsEffectiveTotal.value ? (fullResultsPage.value - 1) * fullResultsPageSize.value + 1 : 0)
const fullResultsEnd = computed(() => Math.min(fullResultsPage.value * fullResultsPageSize.value, fullResultsEffectiveTotal.value))
const fullResultsPageItems = computed(() => {
  if (fullResultsMode.value !== 'strategy') return fullResultsItems.value
  const start = (fullResultsPage.value - 1) * fullResultsPageSize.value
  return fullResultsItems.value.slice(start, start + fullResultsPageSize.value)
})
const fullResultsTitle = computed(() => {
  const turn = fullResultsTurn.value
  if (turn?.agentPlan?.tool === 'strategy_select' || turn?.result?.strategy) return '策略完整列表'
  return '筛选完整列表'
})
const fullResultsSub = computed(() => {
  const total = fullResultsTotal.value || 0
  const loaded = fullResultsItems.value.length
  if (fullResultsMode.value === 'strategy' && total > loaded) return `已加载前 ${loaded} / ${total} 只`
  return `共 ${total} 只`
})
const showResultsPageLink = computed(() => fullResultsMode.value === 'screen')

function strategyIdForTurn(turn) {
  return turn?.result?.strategy?.id || turn?.agentPlan?.strategy_id || null
}

function conditionsForTurn(turn) {
  return turn?.result?.parsed_conditions || turn?.parsedConditions || parsedConditions.value || []
}

function closeFullResults() {
  fullResultsOpen.value = false
  fullResultsError.value = ''
}

function pageSizeClass(size) {
  return size === fullResultsPageSize.value ? 'active' : ''
}

async function setFullResultsPageSize(size) {
  if (size === fullResultsPageSize.value) return
  fullResultsPageSize.value = size
  await loadFullResultsPage(1)
}

// 0 命中时给具体可操作建议，根据已解析的条件挑最严的一条
const zeroResultHint = computed(() => {
  const cs = parsedConditions.value
  if (!cs.length) return '试着把条件描述得更具体一些'
  // 优先去掉 industry / market 这种枚举型
  const enumCond = cs.find((c) => c.field === 'industry' || c.field === 'market')
  if (enumCond) return `当前数据池可能不含「${Array.isArray(enumCond.value) ? enumCond.value.join(' / ') : enumCond.value}」，可以去掉行业限制再试`
  // 其次找数值最严的
  const tight = cs.find((c) => c.op === 'lt' || c.op === 'lte') || cs[0]
  return `条件可能太严格，例如 "${tight.field} ${opLabel[tight.op] || tight.op} ${tight.value}" 放宽一些试试`
})

// 思考预览只显示最后 ~120 字（多了滚动太抖）；保留首尾换行更自然
const thinkingPreview = computed(() => {
  const s = thinkingBuf.value
  if (s.length <= 200) return s
  return '…' + s.slice(-200)
})
const textOnlyTools = ['strategy_design', 'ask_clarification', 'explain_result', 'stock_detail']
const executionTools = new Set([
  'stock_screen',
  'strategy_select',
  'result_sort',
  'sort_results',
  'paginate_results',
  'stock_detail',
  'explain_result',
  'strategy_design',
])
const isExecutionTool = (tool) => executionTools.has(tool)
const visibleToolCalls = (calls = []) => (calls || []).filter((call) => isExecutionTool(call?.name))
const turnResultItems = (turn) => (turn?.result?.items || []).slice(0, 6)
const hasTurnAnswer = (turn) => Boolean((turn?.agentAnswer || '').trim())
const turnThinkingPreview = (turn) => {
  const s = turn?.thinkingBuf || ''
  return s.length <= 200 ? s : '…' + s.slice(-200)
}
const isDesignTurn = (turn) => turn?.agentPlan?.tool === 'strategy_design'
const isTextOnlyTurn = (turn) => textOnlyTools.includes(turn?.agentPlan?.tool) && !turn?.result
const isStreamingAnswerTurn = (turn) => Boolean(isStreaming.value && hasTurnAnswer(turn) && latestTurn.value?.id === turn?.id)
const turnAgentTitle = (turn) => turn?.agentPlan?.tool_label || 'Agent 结论'
const turnToolLabel = (turn) => turn?.agentPlan?.tool_label || (turn?.result ? '股票筛选' : '待判断')
function agentSourceLabel(plan, aiRuntime = null) {
  if (aiRuntime?.source === 'ai_agent' || aiRuntime?.used === true) return 'AI Agent'
  if (aiRuntime?.source === 'chat_only') return '普通回复'
  if (aiRuntime?.source === 'local_deterministic') return '本地处理'
  if (aiRuntime?.source === 'local_fallback' || aiRuntime?.fallback) return '本地处理'
  if (aiRuntime?.source === 'local_rules' || aiRuntime?.configured === false) return '本地规则'
  if (aiRuntime?.label) return aiRuntime.label
  if (plan?.ai_configured) return '本地处理'
  return '本地规则'
}
const turnSourceLabel = (turn) => agentSourceLabel(turn?.agentPlan, turn?.screenMeta?.ai_status || turn?.aiStatus)
const turnConditionIntro = (turn) => {
  if (turn?.agentPlan?.tool === 'strategy_design') return '建议量化条件'
  if (turn?.agentPlan?.tool === 'explain_result') return '上一轮条件'
  return turn?.result ? `筛选条件 · 命中 ${turn.result.total} 只` : '识别条件'
}
const turnResultTitle = (turn) => turn?.agentPlan?.tool === 'strategy_select' ? '策略选股结果' : '筛选结果'
const emptyResultTitleFor = (turn) => turn?.result?.total > 0 ? '当前页没有更多结果' : '没有命中任何股票'
function zeroResultHintFor(turn) {
  if (turn?.result?.total > 0 && !turn?.result?.items?.length) return '可以打开完整列表查看已有结果，或继续调整排序条件'
  const cs = turn?.parsedConditions || []
  if (!cs.length) return '试着把条件描述得更具体一些'
  const enumCond = cs.find((c) => c.field === 'industry' || c.field === 'market')
  if (enumCond) return `当前数据池可能不含「${Array.isArray(enumCond.value) ? enumCond.value.join(' / ') : enumCond.value}」，可以去掉行业限制再试`
  const tight = cs.find((c) => c.op === 'lt' || c.op === 'lte') || cs[0]
  return `条件可能太严格，例如 "${tight.field} ${opLabel[tight.op] || tight.op} ${tight.value}" 放宽一些试试`
}
const isDesignResponse = computed(() => agentPlan.value?.tool === 'strategy_design')
const isTextOnlyAgent = computed(() => textOnlyTools.includes(agentPlan.value?.tool) && !result.value)
const sourceLabel = computed(() => agentSourceLabel(agentPlan.value, screenMeta.value?.ai_status))
const agentAnswerTitle = computed(() => agentPlan.value?.tool_label || 'Agent 结论')
const agentToolLabel = computed(() => agentPlan.value?.tool_label || (result.value ? '股票筛选' : '待判断'))
const conditionIntro = computed(() => {
  if (agentPlan.value?.tool === 'strategy_design') return '建议量化条件'
  if (agentPlan.value?.tool === 'explain_result') return '上一轮条件'
  return result.value ? `筛选条件 · 命中 ${result.value.total} 只` : '识别条件'
})
const resultTitle = computed(() => agentPlan.value?.tool === 'strategy_select' ? '策略选股结果' : '筛选结果')
function historyTitle(c) {
  return c.title || c.query || '新建对话'
}
function historyMeta(c) {
  const ts = c.updatedAt || c.ts
  return fmtRelTime(ts) || ''
}
function traceDisplay(trace) {
  return String(trace || '')
    .replace(/\([^)]*(?:conditions|limit|offset|strategy_id)=[^)]*\)/g, '')
    .replace(/offset=\d+/g, '下一批结果')
    .replace(/^tool_router -> /, '选择工具：')
    .replace('选择工具：strategy_design', '选择工具：策略设计')
    .replace('选择工具：stock_screen', '选择工具：股票筛选')
    .replace('选择工具：strategy_select', '选择工具：策略选股')
    .replace('选择工具：explain_result', '选择工具：结果解释')
    .replace('选择工具：stock_detail', '选择工具：个股详情')
    .replace('选择工具：ask_clarification', '选择工具：补充追问')
    .replace(/^调用 screener_engine\.screen/, '执行股票筛选')
    .replace(/^调用 strategy_selector\.run_strategy_selection/, '执行策略选股')
    .replace(/^跳过 screener_engine\.screen：/, '未执行股票筛选：')
    .replace(/^未调用 screener_engine\.screen：/, '未执行股票筛选：')
}

const turnToolCallRows = (turn) => visibleToolCalls(turn?.toolCalls || [])

function detailTargetFromToolCalls(calls = []) {
  return (calls || []).find((call) => call?.name === 'stock_detail' && call?.result?.code)?.result || null
}

function detailBasicsFromToolCalls(calls = []) {
  const target = detailTargetFromToolCalls(calls)
  return target?.basics || null
}

function turnDetailTarget(turn) {
  return detailTargetFromToolCalls(turn?.toolCalls)
}

function turnDetailBasics(turn) {
  return detailBasicsFromToolCalls(turn?.toolCalls)
}

function openDetailTarget(target) {
  if (target?.code) router.push(`/detail/${target.code}`)
}

async function send() {
  const q = input.value.trim()
  if (!q) return
  await streamSend(q)
  if (phase.value === 'done') input.value = ''
}

function pickPreset(p) {
  input.value = p
  send()
}

function restoreFromHistory(id) {
  if (streamRestore(id)) history.activate(id)
}

async function openFullResults(turn = latestTurn.value) {
  if (!turn?.result) return
  fullResultsTurn.value = turn
  fullResultsOpen.value = true
  fullResultsError.value = ''
  fullResultsItems.value = []
  fullResultsTotal.value = turn.result.total || 0
  fullResultsTradeDate.value = turn.result.trade_date || null
  fullResultsPage.value = 1
  fullResultsMode.value = strategyIdForTurn(turn) ? 'strategy' : 'screen'
  await loadFullResultsPage(1)
}

async function loadFullResultsPage(nextPage = fullResultsPage.value) {
  const turn = fullResultsTurn.value
  if (!turn?.result) return
  fullResultsLoading.value = true
  fullResultsError.value = ''
  try {
    const strategyId = strategyIdForTurn(turn)
    fullResultsPage.value = Math.max(1, nextPage)
    if (strategyId) {
      const wanted = Math.min(Math.max(turn.result.total || fullResultsPageSize.value, fullResultsPageSize.value), 1000)
      const data = await selectStrategy(strategyId, { limit: wanted, notify: false })
      fullResultsMode.value = 'strategy'
      fullResultsItems.value = data.items || []
      fullResultsTotal.value = data.total || fullResultsItems.value.length
      fullResultsTradeDate.value = data.trade_date || turn.result.trade_date || null
      return
    }

    const plan = turn.agentPlan || agentPlan.value
    const sortBy = turn?.screenMeta?.sort_by || plan?.sort_by || screenMeta.value?.sort_by || 'market_cap'
    const sortDesc = (turn?.screenMeta?.sort_desc ?? plan?.sort_desc ?? screenMeta.value?.sort_desc) !== false
    const conditions = conditionsForTurn(turn)
    const data = await screen(conditions, {
      sort_by: sortBy,
      sort_desc: sortDesc,
      offset: (fullResultsPage.value - 1) * fullResultsPageSize.value,
      limit: fullResultsPageSize.value,
    })
    fullResultsMode.value = 'screen'
    fullResultsItems.value = data.items || []
    fullResultsTotal.value = data.total || 0
    fullResultsTradeDate.value = data.trade_date || turn.result.trade_date || null
  } catch (e) {
    fullResultsError.value = e?.response?.data?.detail || e?.message || '完整列表加载失败'
  } finally {
    fullResultsLoading.value = false
  }
}

async function changeFullResultsPage(nextPage) {
  const safePage = Math.min(Math.max(1, nextPage), fullResultsPageCount.value)
  if (fullResultsMode.value === 'strategy') {
    fullResultsPage.value = safePage
    return
  }
  await loadFullResultsPage(safePage)
}

async function openResultsPage(turn = latestTurn.value) {
  const plan = turn?.agentPlan || agentPlan.value
  const turnResult = turn?.result || result.value || null
  const sortBy = turn?.screenMeta?.sort_by || plan?.sort_by || screenMeta.value?.sort_by || 'market_cap'
  const sortDesc = (turn?.screenMeta?.sort_desc ?? plan?.sort_desc ?? screenMeta.value?.sort_desc) !== false
  const remoteSession = await history.ensureRemote?.(history.activeId)
  const fallbackContextId = [
    history.activeId && history.activeId !== '__new__' ? history.activeId : null,
    turn?.id || Date.now().toString(36),
  ].filter(Boolean).join(':')
  const contextId = remoteSession?.contextId || turn?.contextId || fallbackContextId || Date.now().toString(36)
  const payload = JSON.stringify({
    version: 1,
    context_id: contextId,
    server_session_id: remoteSession?.serverId || null,
    session_id: history.activeId && history.activeId !== '__new__' ? history.activeId : null,
    turn_id: turn?.id || null,
    query: turn?.query || lastQuery.value,
    conditions: turn?.parsedConditions || parsedConditions.value,
    sort_by: sortBy,
    sort_desc: sortDesc,
    page: 1,
    size: 20,
    total: turnResult?.total || 0,
    last_result: turnResult
      ? {
          total: turnResult.total || 0,
          offset: turnResult.offset || 0,
          limit: turnResult.limit || 50,
          trade_date: turnResult.trade_date || null,
          items: (turnResult.items || []).slice(0, 8),
          parsed_conditions: turnResult.parsed_conditions || turn?.parsedConditions || parsedConditions.value,
        }
      : null,
  })
  try {
    sessionStorage.setItem(`${AGENT_RESULTS_KEY}:${contextId}`, payload)
    sessionStorage.setItem(AGENT_RESULTS_KEY, payload)
  } catch { /* ignore storage quota */ }
  try {
    localStorage.setItem(`${AGENT_RESULTS_KEY}:${contextId}`, payload)
    localStorage.setItem(AGENT_RESULTS_KEY, payload)
  } catch { /* ignore storage quota */ }
  router.push({
    path: '/results',
    query: { source: 'agent', ctx: contextId, page: '1', size: '20', sort: sortBy, order: sortDesc ? 'desc' : 'asc' },
  })
}

function newSession() {
  if (isStreaming.value) stop()
  clearThread()
  input.value = ''
}

function openChatHomeState() {
  newSession()
}

function retryTurn(turn) {
  if (!turn?.query || isStreaming.value) return
  input.value = turn.query
  send()
}

function clearChatRouteQuery() {
  window.history.replaceState(window.history.state, '', '/chat')
}

function deleteHistory(id, ev) {
  ev?.stopPropagation()
  history.remove(id)
}

function fmtRelTime(ts) {
  const now = Date.now() / 1000
  const diff = now - ts
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  const d = new Date(ts * 1000)
  const today = new Date()
  if (d.toDateString() === today.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return `${d.getMonth() + 1}-${d.getDate()}`
}

async function consumeRouteIntent() {
  const sessionId = route.query.session
  if (sessionId && typeof sessionId === 'string') {
    streamRestore(sessionId)
    router.replace({ path: '/chat' })
    return
  }
  if (route.query.fresh) {
    openChatHomeState()
    router.replace({ path: '/chat' })
    return
  }
  const q = route.query.q
  if (q && typeof q === 'string') {
    input.value = q
    const run = route.query.run === '1' || route.query.run === 'true'
    if (run) {
      await send()
    }
    // 普通预填立即清 URL；自动执行等发送完成后再清，避免切页时丢掉流式状态。
    clearChatRouteQuery()
  }
}

// 从其他页面跳转携带 ?q=xxx&run=1 时自动发送；普通 ?q=xxx 只预填。
// 导航点击 AI选股携带 ?fresh=... 时回到起始态。
onMounted(() => {
  window.addEventListener('qwen-chat-home', openChatHomeState)
  consumeRouteIntent()
})
onBeforeUnmount(() => {
  window.removeEventListener('qwen-chat-home', openChatHomeState)
})
watch(() => route.fullPath, consumeRouteIntent)

watch(
  () => conversationTurns.value.map((turn) => [
    turn.id,
    turn.phase,
    turn.query,
    turn.thinkingBuf,
    turn.agentAnswer,
    turn.result?.total,
  ].join('|')).join('::'),
  () => {
    nextTick(() => {
      const el = chatScroll.value
      if (el) el.scrollTop = el.scrollHeight
    })
  },
  { flush: 'post' }
)

watch(
  () => fullResultsPageItems.value.map((s) => s.code).join('|'),
  () => {
    if (fullResultsOpen.value) loadSparks(fullResultsPageItems.value.map((s) => s.code))
  }
)

// ---- 右侧 inspector：每阶段对应一行 ----
const stages = computed(() => {
  const items = []
  const elapsed = (a, b) => (b > a ? `${((b - a) / 1000).toFixed(1)}s` : '')
  if (agentPlan.value && agentPlan.value.tool !== 'stock_screen') {
    return [
      {
        t: '工具判断',
        state: 'success',
        out: `选择「${agentToolLabel.value}」`,
        dur: tParsed.value && tStart.value ? elapsed(tStart.value, tParsed.value) : '',
      },
      {
        t: agentToolLabel.value,
        state: 'success',
        out: result.value
          ? `返回 ${result.value.total} 只结果`
          : (isTextOnlyAgent.value ? '未执行股票筛选' : '已完成'),
        dur: tDone.value && tParsed.value ? elapsed(tParsed.value, tDone.value) : '',
      },
    ]
  }
  // 1. 解析
  let s1State = 'pending'
  if (phase.value === 'thinking') s1State = 'running'
  else if (phase.value === 'parsed' || phase.value === 'screening' || phase.value === 'done') s1State = 'success'
  else if (phase.value === 'error' && !parsedConditions.value.length) s1State = 'failed'
  else if (phase.value === 'idle') s1State = 'pending'
  items.push({
    t: '工具判断',
    state: s1State,
    out: parsedConditions.value.length
      ? `选择「${agentToolLabel.value}」，识别 ${parsedConditions.value.length} 个条件`
      : (phase.value === 'thinking' ? '判断中…' : '等待输入'),
    dur: tParsed.value && tStart.value ? elapsed(tStart.value, tParsed.value) : '',
  })
  // 2. 执行筛选
  let s2State = 'pending'
  if (phase.value === 'screening') s2State = 'running'
  else if (phase.value === 'done') s2State = 'success'
  else if (phase.value === 'error' && parsedConditions.value.length) s2State = 'failed'
  items.push({
    t: '股票筛选',
    state: s2State,
    out: result.value ? `命中 ${result.value.total} 只，展示 ${result.value.items.length} 只` : '等待条件确认',
    dur: tDone.value && tParsed.value ? elapsed(tParsed.value, tDone.value) : '',
  })
  return items
})

const stageColor = (s) => ({
  pending: A2.textDim,
  running: A2.qwen,
  success: A2.up,
  failed: A2.down,
}[s] || A2.textDim)
</script>

<template>
  <Shell>
    <div class="ai-page">
      <section class="ai-shell">
        <aside class="history-panel">
          <div class="history-panel-head">
            <div class="history-head-lead">
              <h3 class="history-title">历史会话</h3>
            </div>
            <button class="history-new-btn" type="button" @click="newSession">新建</button>
          </div>

          <div class="history-panel-body">
            <div v-if="!history.items.length" class="history-empty">
              还没有历史会话，从右侧发起第一轮任务。
            </div>

            <template v-for="group in [
              { key: 'today', label: '今天', list: history.grouped.today },
              { key: 'yesterday', label: '昨天', list: history.grouped.yesterday },
              { key: 'thisWeek', label: '本周', list: history.grouped.thisWeek },
              { key: 'earlier', label: '更早', list: history.grouped.earlier },
            ]" :key="group.key">
              <div v-if="group.list.length" class="history-group-label">{{ group.label }}</div>
              <div
                v-for="c in group.list"
                :key="c.id"
                class="session-entry"
                :class="{ active: c.id === history.activeId }"
              >
                <button
                  class="session-item"
                  type="button"
                  :disabled="isStreaming"
                  :title="isStreaming ? '当前对话进行中，请先停止' : historyTitle(c)"
                  @click="restoreFromHistory(c.id)"
                >
                  <div class="session-item-top">
                    <span class="session-name">{{ historyTitle(c) }}</span>
                  </div>
                  <span class="session-meta">{{ historyMeta(c) }}</span>
                </button>
                <button class="session-delete" type="button" title="删除" @click="deleteHistory(c.id, $event)">
                  <Icon name="x" :size="12" />
                </button>
              </div>
            </template>

            <button v-if="history.items.length" class="history-clear-button" @click="history.clear()">
              清空全部历史 ({{ history.items.length }})
            </button>
          </div>
        </aside>

        <main class="main-panel" :class="{ home: !hasConversation }">
          <template v-if="!hasConversation">
            <div class="home-stage">
              <div class="home-hero-copy">
                <p class="home-eyebrow">QWEN STOCK AGENT</p>
                <h1 class="home-heading">用自然语言筛选 A 股</h1>
              </div>

              <form class="composer composer--home" @submit.prevent="send">
                <textarea
                  v-model="input"
                  class="composer-input"
                  rows="1"
                  :disabled="isStreaming"
                  placeholder=""
                  @keydown.enter.exact.prevent="send"
                />
                <div class="composer-bar">
                  <div class="composer-modes">

                  </div>
                  <button class="send-icon-btn" type="submit" :disabled="!canSubmit" title="发送" aria-label="发送">
                    <Icon name="send" :size="15" />
                  </button>
                </div>
              </form>

              <div class="home-prompt-grid">
                <button
                  v-for="t in presetPrompts"
                  :key="t"
                  class="home-prompt-card"
                  type="button"
                  :disabled="isStreaming"
                  @click="!isStreaming && pickPreset(t)"
                >
                  <span class="home-prompt-title">{{ t }}</span>
                </button>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="thread-shell">
              <div ref="chatScroll" class="chat-scroll has-thread">
                <div v-if="!aiStatus.isUp" class="status-banner warning-banner">
                  <Icon name="alert" :size="13" />
                  <span>
                    <strong>AI 暂不可用</strong>
                    <em>{{ aiStatus.reason || 'AI 服务暂时不可达' }}</em>
                  </span>
                  <button class="status-action" type="button" @click="aiStatus.recheck">
                    <Icon name="refresh" :size="11" /> 重新检测
                  </button>
                </div>

                <div class="chat-thread">
                  <article v-for="turn in conversationTurns" :key="turn.id" class="msg-pair">
                    <div class="msg user">
                      <div class="msg-content">{{ turn.query }}</div>
                    </div>

                    <div class="msg assistant">
                      <div class="assistant-head">
                        <span class="assistant-avatar">千</span>
                        <span>{{ turnAgentTitle(turn) }}</span>

                      </div>

                      <div v-if="!turnToolCallRows(turn).length && turn.phase !== 'done' && turn.phase !== 'idle'" class="thinking-line">
                        <Icon name="loader" :size="13" class="spin" />
                        <span>正在分析…</span>
                      </div>

                      <div v-if="turnToolCallRows(turn).length" class="chat-tool-trace">
                        <div class="tool-trace-head">
                          <Icon name="tools" :size="13" />
                          <span>工具调用</span>
                        </div>
                        <div class="tool-call-list">
                          <div v-for="(call, i) in turnToolCallRows(turn)" :key="call.id" class="tool-call" :class="{ pending: call.status === 'running' }">
                            <span class="tool-call-index">
                              <Icon v-if="call.status === 'running'" name="loader" :size="12" class="spin" />
                              <template v-else>{{ i + 1 }}</template>
                            </span>
                            <div class="tool-call-main">
                              <div class="tool-call-name">{{ call.label || call.name }}</div>
                              <div class="tool-call-summary">{{ call.message }}<span v-if="call.status === 'running'" class="tool-dots"></span></div>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div v-if="turn.parsedConditions?.length" class="condition-block">
                        <div class="condition-intro">
                          <template v-if="isDesignTurn(turn)">
                            {{ turnConditionIntro(turn) }}：
                          </template>
                          <template v-else>
                            {{ turnConditionIntro(turn) }}<span v-if="turn.phase === 'screening'">，执行中…</span>：
                          </template>
                        </div>
                        <div class="condition-list">
                          <div
                            v-for="(c, i) in turn.parsedConditions"
                            :key="i"
                            class="cond-chip"
                            :style="{ '--delay': (i * 60) + 'ms' }"
                          >
                            <span>{{ fmtCond(c) }}</span>
                          </div>
                        </div>
                      </div>

                      <div v-if="hasTurnAnswer(turn)" class="msg-content agent-answer-panel" :class="{ compact: isTextOnlyTurn(turn) }">
                        <AiMarkdown
                          :text="turn.agentAnswer"
                          :compact="isTextOnlyTurn(turn)"
                          :streaming="isStreamingAnswerTurn(turn)"
                        />
                        <button
                          v-if="turnDetailTarget(turn)"
                          type="button"
                          class="agent-detail-card"
                          @click="openDetailTarget(turnDetailTarget(turn))"
                        >
                          <template v-if="turnDetailBasics(turn)">
                            <div class="detail-card-head">
                              <span class="detail-card-name">{{ turnDetailBasics(turn).name }}</span>
                              <span class="detail-card-code">{{ turnDetailBasics(turn).code }}</span>
                            </div>
                            <div class="detail-card-meta">
                              <span v-if="turnDetailBasics(turn).industry">{{ turnDetailBasics(turn).industry }}</span>
                              <span v-if="turnDetailBasics(turn).market">{{ turnDetailBasics(turn).market }}</span>
                              <span v-if="turnDetailBasics(turn).trade_date">{{ turnDetailBasics(turn).trade_date }}</span>
                            </div>
                            <div class="detail-card-stats">
                              <span v-if="turnDetailBasics(turn).close != null" class="detail-stat">
                                <em>{{ turnDetailBasics(turn).close?.toFixed(2) }}</em> 收盘
                              </span>
                              <span v-if="turnDetailBasics(turn).pe != null" class="detail-stat">
                                <em>{{ turnDetailBasics(turn).pe?.toFixed(1) }}</em> PE
                              </span>
                              <span v-if="turnDetailBasics(turn).pb != null" class="detail-stat">
                                <em>{{ turnDetailBasics(turn).pb?.toFixed(2) }}</em> PB
                              </span>
                              <span v-if="turnDetailBasics(turn).market_cap != null" class="detail-stat">
                                <em>{{ turnDetailBasics(turn).market_cap?.toFixed(0) }}亿</em> 市值
                              </span>
                              <span v-if="turnDetailBasics(turn).dividend_yield != null" class="detail-stat">
                                <em>{{ turnDetailBasics(turn).dividend_yield?.toFixed(2) }}%</em> 股息率
                              </span>
                            </div>
                          </template>
                          <div class="detail-card-action">
                            打开详情页 <Icon name="arrowRight" :size="12" />
                          </div>
                        </button>
                      </div>


                      <div v-if="turn.phase === 'error'" class="error-card">
                        <Icon name="shield" :size="14" />
                        <div>{{ turn.errorMsg }}</div>
                        <button class="btn-outline" @click="retryTurn(turn)">
                          <Icon name="refresh" :size="11" /> 重试
                        </button>
                      </div>

                      <div v-if="turn.result" class="result-preview">
                        <div class="result-preview-head">
                          <div>
                            <div class="result-preview-title">{{ turnResultTitle(turn) }}</div>
                            <div class="result-preview-sub">命中 <strong>{{ turn.result.total }}</strong> 只 · 预览前 {{ turnResultItems(turn).length }} 只</div>
                          </div>
                          <button class="result-preview-more" @click="openFullResults(turn)">
                            完整列表 <Icon name="arrowRight" :size="12" />
                          </button>
                        </div>
                        <div v-if="turn.result.items.length" class="result-preview-list">
                          <button
                            v-for="(s, i) in turnResultItems(turn)"
                            :key="s.code"
                            type="button"
                            class="result-preview-row"
                            @click="router.push(`/detail/${s.code}`)"
                          >
                            <span class="result-rank">{{ String(i + 1).padStart(2, '0') }}</span>
                            <span class="result-stock">
                              <strong>{{ s.name }}</strong>
                              <small>{{ s.code }}</small>
                            </span>
                            <span class="result-industry">{{ s.industry || '—' }}</span>
                            <span class="result-facts">
                              <small v-for="fact in resultFacts(s)" :key="fact">{{ fact }}</small>
                            </span>
                            <span class="result-price">
                              <strong>{{ fmtMetric(s.close) }}</strong>
                              <small :style="{ color: s.change_pct > 0 ? '#E04F76' : s.change_pct < 0 ? '#16A35C' : '#A1A1AA' }">{{ fmtChange(s.change_pct) }}</small>
                            </span>
                            <span class="result-trend"><Sparkline :data="spark(s.code)" :color="s.change_pct >= 0 ? '#C8312A' : '#0E8A66'" :fill="s.change_pct >= 0 ? '#C8312A22' : '#0E8A6622'" :width="72" :height="20" /></span>
                          </button>
                        </div>
                        <EmptyState v-else icon="filter" :title="emptyResultTitleFor(turn)" :subtitle="zeroResultHintFor(turn)" />
                      </div>
                    </div>
                  </article>
                </div>
              </div>

              <div class="composer-dock">
                <form class="composer composer--thread" @submit.prevent="send">
                  <textarea
                    v-model="input"
                    class="composer-input"
                    rows="1"
                    :disabled="isStreaming"
                    placeholder="给千问 Agent 发送消息"
                    @keydown.enter.exact.prevent="send"
                  />
                  <div class="composer-bar">
                    <div class="composer-modes"></div>
                    <button v-if="isStreaming" class="send-icon-btn stop" type="button" title="停止" aria-label="停止" @click="stop">
                      <Icon name="x" :size="15" />
                    </button>
                    <button v-else class="send-icon-btn" type="submit" :disabled="!canSubmit" title="发送" aria-label="发送">
                      <Icon name="send" :size="15" />
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </template>
        </main>
      </section>

      <Transition name="full-results-fade">
        <div v-if="fullResultsOpen" class="full-results-overlay" @click.self="closeFullResults">
          <section class="full-results-modal" role="dialog" aria-modal="true" :aria-label="fullResultsTitle">
            <header class="full-results-head">
              <div>
                <p class="full-results-eyebrow">{{ fullResultsMode === 'strategy' ? 'BUILT-IN STRATEGY' : 'STRUCTURED SCREEN' }}</p>
                <h3>{{ fullResultsTitle }}</h3>
                <div class="full-results-meta">
                  <span>{{ fullResultsSub }}</span>
                  <span v-if="fullResultsTradeDate">数据日期 {{ fullResultsTradeDate }}</span>
                </div>
              </div>
              <div class="full-results-actions">
                <button v-if="showResultsPageLink" type="button" class="full-results-secondary" @click="openResultsPage(fullResultsTurn)">
                  打开结果页
                </button>
                <button type="button" class="full-results-close" aria-label="关闭完整列表" @click="closeFullResults">
                  <Icon name="x" :size="16" />
                </button>
              </div>
            </header>

            <div class="full-results-toolbar">
              <div class="full-results-query">{{ fullResultsTurn?.query || lastQuery }}</div>
              <div class="full-results-page-sizes">
                <button
                  v-for="size in [50, 100]"
                  :key="size"
                  type="button"
                  :class="pageSizeClass(size)"
                  :disabled="fullResultsLoading"
                  @click="setFullResultsPageSize(size)"
                >
                  {{ size }} / 页
                </button>
              </div>
            </div>

            <div v-if="fullResultsError" class="full-results-error">
              <Icon name="alert" :size="14" />
              <span>{{ fullResultsError }}</span>
              <button type="button" @click="loadFullResultsPage(fullResultsPage)">重试</button>
            </div>

            <div class="full-results-table-wrap" :class="{ loading: fullResultsLoading }">
              <div class="full-results-table-head">
                <span>#</span>
                <span>名称 / 代码</span>
                <span>行业 / 信号</span>
                <span>关键指标</span>
                <span>价格</span>
                <span>走势</span>
              </div>

              <div v-if="fullResultsLoading && !fullResultsPageItems.length" class="full-results-loading">
                <div v-for="n in 8" :key="n" class="full-results-skeleton"></div>
              </div>

              <div v-else-if="fullResultsPageItems.length" class="full-results-table-body">
                <button
                  v-for="(s, i) in fullResultsPageItems"
                  :key="s.code"
                  type="button"
                  class="full-results-row"
                  @click="router.push(`/detail/${s.code}`)"
                >
                  <span class="full-results-rank mono">
                    {{ String(fullResultsStart + i).padStart(2, '0') }}
                  </span>
                  <span class="full-results-stock">
                    <strong>{{ s.name || s.code }}</strong>
                    <small>{{ s.code }}</small>
                  </span>
                  <span class="full-results-industry">
                    <em>{{ s.industry || s.market || '—' }}</em>
                    <small v-if="s.signals?.length">{{ s.signals.slice(0, 2).join(' / ') }}</small>
                  </span>
                  <span class="full-results-facts">
                    <small v-for="fact in resultFacts(s)" :key="fact">{{ fact }}</small>
                  </span>
                  <span class="full-results-price">
                    <strong>{{ fmtMetric(s.close) }}</strong>
                    <small :class="{ up: s.change_pct > 0, down: s.change_pct < 0 }">{{ fmtChange(s.change_pct) }}</small>
                  </span>
                  <span class="full-results-spark">
                    <Sparkline
                      :data="spark(s.code)"
                      :color="s.change_pct >= 0 ? '#C8312A' : '#0E8A66'"
                      :fill="s.change_pct >= 0 ? '#C8312A22' : '#0E8A6622'"
                      :width="84"
                      :height="22"
                    />
                  </span>
                </button>
              </div>

              <EmptyState v-else icon="filter" title="没有命中任何股票" subtitle="可以调整条件或返回对话继续收窄/放宽目标" />
            </div>

            <footer class="full-results-foot">
              <span>
                第 {{ fullResultsStart }}–{{ fullResultsEnd }} 条
                <template v-if="fullResultsMode === 'strategy' && fullResultsTotal > fullResultsItems.length">
                  · 当前最多载入 {{ fullResultsItems.length }} 条
                </template>
              </span>
              <div class="full-results-pager">
                <button type="button" :disabled="fullResultsLoading || fullResultsPage <= 1" @click="changeFullResultsPage(fullResultsPage - 1)">
                  上一页
                </button>
                <span>{{ fullResultsPage }} / {{ fullResultsPageCount }}</span>
                <button type="button" :disabled="fullResultsLoading || fullResultsPage >= fullResultsPageCount" @click="changeFullResultsPage(fullResultsPage + 1)">
                  下一页
                </button>
              </div>
            </footer>
          </section>
        </div>
      </Transition>
    </div>
  </Shell>
</template>

<style scoped>
.chat-workbench {
  height: clamp(600px, calc(100vh - 114px), 760px);
  min-height: 0;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr) 320px;
  overflow: hidden;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
}

.chat-sidebar,
.chat-inspector {
  min-width: 0;
  overflow: auto;
  background: #F7F7F7;
}

.chat-sidebar {
  padding: 14px;
  border-right: 1px solid #EDEDED;
  font-size: 12px;
}

.new-chat-button {
  display: flex;
  width: 100%;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 16px;
  padding: 10px 12px;
  border: 0;
  border-radius: 8px;
  background: #111111;
  color: #FFFFFF;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  transition: background 0.18s, transform 0.18s;
}

.new-chat-button:hover {
  background: #000000;
}

.new-chat-button:active {
  transform: translateY(1px);
}

.history-empty-state {
  padding: 10px;
  border: 1px dashed #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
  color: #71717A;
  font-size: 11px;
  line-height: 1.55;
  text-align: center;
}

.history-group-label {
  margin: 12px 0 6px;
  padding-left: 4px;
  color: #A1A1AA;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.2px;
}

.history-clear-button {
  width: 100%;
  margin-top: 12px;
  padding: 7px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #71717A;
  cursor: pointer;
  font-size: 10.5px;
}

.history-clear-button:hover {
  background: #EFEDE6;
  color: #111111;
}

.prompt-bank {
  display: grid;
  gap: 6px;
  margin-top: 22px;
  padding: 12px;
  
  background: #FFFFFF;
}

.prompt-bank-title {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 2px;
  color: #111111;
  font-size: 11px;
  font-weight: 700;
}

.prompt-item {
  width: 100%;
  padding: 7px 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: #F7F7F7;
  color: #3F3F46;
  cursor: pointer;
  font-size: 11px;
  line-height: 1.45;
  text-align: left;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
}

.prompt-item:hover:not(:disabled) {
  border-color: #D8D8D8;
  background: #FFFFFF;
  color: #111111;
}

.prompt-item:disabled {
  cursor: wait;
  opacity: 0.5;
}

.chat-main {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #FFFFFF;
}

.chat-header {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  border-bottom: 1px solid #EDEDED;
  background: #FFFFFF;
}

.chat-header-copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.chat-header-title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #111111;
  font-size: 13px;
  font-weight: 800;
}

.chat-header-sub {
  overflow: hidden;
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-header-meta {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
}

.chat-header-meta span {
  padding: 4px 7px;
  border: 1px solid #EDEDED;
  border-radius: 999px;
  background: #F7F7F7;
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  font-weight: 700;
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 24px;
  background:
    linear-gradient(#FFFFFF, #FFFFFF) padding-box,
    linear-gradient(180deg, rgba(36, 86, 216, 0.035), rgba(255, 255, 255, 0)) border-box;
}

.composer-shell {
  padding: 12px 16px 14px;
  border-top: 1px solid #EDEDED;
  background: #F7F7F7;
}

.composer-card {
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 10px;
  background: #FFFFFF;
  box-shadow: 0 8px 22px rgba(14, 14, 12, 0.06);
}

.composer-input {
  width: 100%;
  height: 38px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #111111;
  font-family: "IBM Plex Sans", "Noto Sans SC", sans-serif;
  font-size: 13px;
  line-height: 1.55;
  resize: none;
}

.composer-input:disabled {
  opacity: 0.6;
}

.composer-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 9px;
  border-top: 1px solid #EDEDED;
}

.composer-status {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 5px;
  overflow: hidden;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-status.warning {
  color: #987400;
}

.status-dot {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #B8FF2C;
}

.composer-spacer {
  flex: 1;
}

.composer-action {
  display: flex;
  min-height: 32px;
  align-items: center;
  gap: 5px;
  padding: 7px 14px;
  border: 0;
  border-radius: 7px;
  color: #FFFFFF;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  transition: background 0.18s, opacity 0.18s, transform 0.18s;
}

.composer-action.send {
  background: #111111;
}

.composer-action.stop {
  background: #3F3D38;
}

.composer-action:hover:not(:disabled) {
  background: #000000;
}

.composer-action:active:not(:disabled) {
  transform: translateY(1px);
}

.composer-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.chat-inspector {
  padding: 16px;
  border-left: 1px solid #EDEDED;
  font-size: 11px;
}

.inspector-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  color: #111111;
  font-size: 12px;
  font-weight: 800;
}

.inspector-title span {
  margin-left: auto;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  font-weight: 700;
}

.inspector-empty {
  color: #71717A;
  font-size: 11px;
  line-height: 1.6;
}

.inspector-meta {
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
  color: #3F3F46;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10.5px;
  line-height: 1.6;
}

.inspector-meta-title {
  margin-bottom: 4px;
  color: #A1A1AA;
  font-size: 9.5px;
  letter-spacing: 1px;
}

.new-chat-button:focus-visible,
.history-clear-button:focus-visible,
.prompt-item:focus-visible,
.composer-action:focus-visible,
.result-preview-more:focus-visible,
.agent-detail-card:focus-visible,
.result-preview-row:focus-visible {
  outline: 2px solid rgba(36, 86, 216, 0.42);
  outline-offset: 2px;
}

.starter-panel {
  width: min(100%, 760px);
  margin-bottom: 16px;
  padding: 14px;
  
  background: #F7F7F7;
}

.chat-scroll:not(.has-thread) .starter-panel {
  margin: 0 auto 18px;
}

.starter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.starter-grid button {
  min-height: 34px;
  padding: 8px 10px;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  font-size: 11.5px;
  line-height: 1.4;
  text-align: left;
}

.starter-grid button:hover {
  border-color: #D8D8D8;
  color: #111111;
  background: #F5F5F5;
}

.chat-scroll:not(.has-thread) {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.conversation-list {
  display: grid;
  gap: 18px;
  padding-bottom: 8px;
}

.conversation-turn {
  display: grid;
  gap: 12px;
}

.user-message {
  display: flex;
  justify-content: flex-end;
}

.user-bubble {
  max-width: min(70%, 720px);
  padding: 12px 16px;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
  color: #111111;
  font-size: 13px;
  line-height: 1.65;
  box-shadow: 0 2px 10px rgba(14, 14, 12, 0.04);
}

.assistant-row {
  display: flex;
  gap: 12px;
}

.assistant-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  place-items: center;
  border-radius: 8px;
  background: linear-gradient(135deg, #111111, #3F3D38);
  color: #FFFFFF;
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 2px 6px rgba(14, 14, 12, 0.10);
}

.thinking-card {
  flex: 1;
  padding: 12px 14px;
  
  background: #FFFFFF;
  color: #71717A;
  font-size: 12px;
}

.thinking-head {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #111111;
  font-weight: 600;
}

.thinking-preview {
  max-height: 120px;
  margin: 8px 0 0 0;
  overflow: hidden;
  padding: 8px 10px;
  border-radius: 5px;
  background: #F7F7F7;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10.5px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.condition-intro {
  margin-left: 40px;
  color: #2F3137;
  font-size: 13.5px;
  line-height: 1.75;
}

.condition-intro span {
  color: #71717A;
  font-weight: 500;
}

.condition-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-left: 40px;
}

.condition-list .cond-chip {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 12px;
  border: 1px solid #EDEDED;
  border-radius: 4px;
  background: #FFFFFF;
  box-shadow: 0 1px 4px rgba(14, 14, 12, 0.03);
  font-size: 11.5px;
}

.condition-list .cond-chip span {
  font-family: "IBM Plex Mono", monospace;
  font-weight: 600;
}

.screening-card {
  margin-left: 40px;
  overflow: hidden;
  
  background: #FFFFFF;
  box-shadow: 0 2px 10px rgba(14, 14, 12, 0.04);
}

.screening-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 13px 16px;
  border-bottom: 1px solid #EDEDED;
  color: #71717A;
  font-size: 12px;
}

.screening-row {
  display: grid;
  grid-template-columns: 36px 1fr 80px 80px 80px;
  gap: 12px;
  align-items: center;
  padding: 11px 16px;
  border-top: 1px solid #F1F1F1;
}

.screening-row:first-of-type {
  border-top: 0;
}

.screening-row .sk-bar {
  height: 12px;
  border-radius: 3px;
}

.screening-row .sk-bar.wide {
  width: 60%;
  height: 14px;
}

.error-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-left: 40px;
  padding: 12px 16px;
  border-radius: 8px;
  background: rgba(23, 138, 85, 0.10);
  color: #178A55;
  font-size: 12px;
}

.agent-answer-panel {
  margin-left: 40px;
  margin-bottom: 20px;
  padding: 14px 16px;
  
  background: #FFFFFF;
  color: #2F3137;
  font-size: 12.5px;
  line-height: 1.75;
  box-shadow: 0 2px 10px rgba(14, 14, 12, 0.04);
}

.agent-answer-title {
  margin-bottom: 8px;
  color: #111111;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.agent-answer-title em {
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  font-style: normal;
  font-weight: 600;
}

.agent-detail-card {
  display: block;
  width: 100%;
  margin-top: 10px;
  border: 1px solid #E4E4E7;
  border-radius: 6px;
  background: #FFFFFF;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: border-color 0.18s, box-shadow 0.18s;
  overflow: hidden;
}
.agent-detail-card:hover {
  border-color: #A1A1AA;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.detail-card-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 10px 12px 4px;
}
.detail-card-name {
  font-size: 14px;
  font-weight: 700;
  color: #18181B;
}
.detail-card-code {
  font-size: 11px;
  color: #A1A1AA;
  font-family: 'IBM Plex Mono', 'JetBrains Mono', monospace;
}
.detail-card-meta {
  display: flex;
  gap: 8px;
  padding: 0 12px 6px;
  font-size: 11px;
  color: #71717A;
}
.detail-card-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 12px;
  border-top: 1px solid #F4F4F5;
  background: #FAFAFA;
}
.detail-stat {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  padding: 2px 6px;
  border-radius: 3px;
  background: #FFFFFF;
  font-size: 10px;
  color: #71717A;
}
.detail-stat em {
  font-style: normal;
  font-weight: 700;
  font-size: 12px;
  color: #18181B;
}
.detail-card-action {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 0;
  border-top: 1px solid #E4E4E7;
  font-size: 11px;
  font-weight: 600;
  color: #3F3F46;
  background: #FAFAFA;
  transition: background 0.18s, color 0.18s;
}
.agent-detail-card:hover .detail-card-action {
  background: #F4F4F5;
  color: #18181B;
}

.result-preview {
  margin: 0 0 20px 40px;
  overflow: hidden;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
  box-shadow: 0 2px 10px rgba(14, 14, 12, 0.04);
}

.result-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid #EDEDED;
  background: #FBFBF9;
}

.result-preview-title {
  color: #111111;
  font-size: 13px;
  font-weight: 700;
}

.result-preview-sub {
  margin-top: 2px;
  color: #71717A;
  font-size: 11px;
}

.result-preview-sub strong {
  color: #111111;
  font-family: "IBM Plex Mono", monospace;
}

.result-preview-more {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 9px;
  border: 1px solid #D8D8D8;
  border-radius: 4px;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
}

.result-preview-more:hover {
  border-color: #B8B8B8;
  background: #F5F5F5;
  color: #111111;
}

.result-preview-row {
  display: grid;
  grid-template-columns: 26px minmax(112px, 1fr) 76px minmax(148px, 1.2fr) 72px 78px;
  gap: 10px;
  width: 100%;
  min-height: 58px;
  align-items: center;
  padding: 10px 14px;
  border: 0;
  border-top: 1px solid #F1F1F1;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  text-align: left;
  transition: background 0.18s;
}

.result-preview-row:first-child {
  border-top: 0;
}

.result-preview-row:hover {
  background: #FAFAFA;
}

.result-rank,
.result-stock small,
.result-price,
.result-price small {
  font-family: "IBM Plex Mono", monospace;
}

.result-rank {
  color: #A1A1AA;
  font-size: 10px;
}

.result-stock,
.result-price {
  display: grid;
  gap: 3px;
}

.result-stock strong {
  overflow: hidden;
  color: #111111;
  font-size: 12.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-stock small,
.result-price small {
  color: #A1A1AA;
  font-size: 10px;
}

.result-industry {
  overflow: hidden;
  color: #71717A;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.result-facts small {
  padding: 2px 4px;
  border-radius: 3px;
  background: #F5F5F5;
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 9.5px;
}

.result-price {
  text-align: right;
}

.result-price strong {
  color: #111111;
  font-size: 12px;
}

.full-results-fade-enter-active,
.full-results-fade-leave-active {
  transition: opacity 0.18s ease;
}

.full-results-fade-enter-from,
.full-results-fade-leave-to {
  opacity: 0;
}

.full-results-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(17, 17, 17, 0.42);
}

.full-results-modal {
  width: min(1120px, calc(100vw - 32px));
  height: min(760px, calc(100vh - 48px));
  display: grid;
  grid-template-rows: auto auto auto 1fr auto;
  overflow: hidden;
  border-radius: 8px;
  background: #FFFFFF;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.24);
}

.full-results-head,
.full-results-toolbar,
.full-results-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.full-results-head {
  padding: 18px 20px 14px;
  border-bottom: 1px solid #EDEDED;
}

.full-results-eyebrow {
  margin: 0 0 4px;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0;
}

.full-results-head h3 {
  margin: 0;
  color: #111111;
  font-size: 18px;
  line-height: 1.25;
}

.full-results-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
  color: #71717A;
  font-size: 12px;
}

.full-results-actions,
.full-results-page-sizes,
.full-results-pager {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.full-results-secondary,
.full-results-close,
.full-results-page-sizes button,
.full-results-pager button,
.full-results-error button {
  appearance: none;
  border: 1px solid #D8D8D8;
  border-radius: 6px;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.full-results-secondary {
  height: 34px;
  padding: 0 12px;
}

.full-results-close {
  width: 34px;
  height: 34px;
  display: inline-grid;
  place-items: center;
  padding: 0;
}

.full-results-secondary:hover,
.full-results-close:hover,
.full-results-page-sizes button:hover,
.full-results-pager button:hover,
.full-results-error button:hover {
  border-color: #B8B8B8;
  background: #F5F5F5;
  color: #111111;
}

.full-results-pager button:disabled,
.full-results-page-sizes button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.full-results-toolbar {
  min-height: 50px;
  padding: 10px 20px;
  border-bottom: 1px solid #F1F1F1;
  background: #FBFBF9;
}

.full-results-query {
  min-width: 0;
  overflow: hidden;
  color: #3F3F46;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.full-results-page-sizes button {
  height: 30px;
  padding: 0 9px;
}

.full-results-page-sizes button.active {
  border-color: #111111;
  background: #111111;
  color: #FFFFFF;
}

.full-results-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 20px 0;
  padding: 10px 12px;
  border-radius: 6px;
  background: rgba(200, 49, 42, 0.08);
  color: #C8312A;
  font-size: 12px;
}

.full-results-error button {
  height: 28px;
  margin-left: auto;
  padding: 0 10px;
}

.full-results-table-wrap {
  min-height: 0;
  overflow: hidden;
}

.full-results-table-head,
.full-results-row {
  display: grid;
  grid-template-columns: 48px minmax(132px, 1.05fr) minmax(132px, 1.1fr) minmax(190px, 1.4fr) 96px 108px;
  gap: 12px;
  align-items: center;
}

.full-results-table-head {
  height: 38px;
  padding: 0 20px;
  border-bottom: 1px solid #EDEDED;
  color: #71717A;
  font-size: 11px;
  font-weight: 700;
}

.full-results-table-body {
  height: calc(100% - 38px);
  overflow: auto;
}

.full-results-row {
  width: 100%;
  min-height: 58px;
  padding: 9px 20px;
  border: 0;
  border-bottom: 1px solid #F1F1F1;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  text-align: left;
  transition: background 0.16s ease;
}

.full-results-row:hover {
  background: #FAFAFA;
}

.full-results-rank,
.full-results-stock small,
.full-results-price,
.full-results-price small,
.full-results-pager span {
  font-family: "IBM Plex Mono", monospace;
}

.full-results-rank {
  color: #A1A1AA;
  font-size: 11px;
}

.full-results-stock,
.full-results-industry,
.full-results-price {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.full-results-stock strong,
.full-results-industry em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.full-results-stock strong {
  color: #111111;
  font-size: 13px;
}

.full-results-stock small,
.full-results-industry small,
.full-results-price small {
  color: #A1A1AA;
  font-size: 10px;
}

.full-results-industry em {
  color: #3F3F46;
  font-size: 12px;
  font-style: normal;
  font-weight: 650;
}

.full-results-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.full-results-facts small {
  max-width: 100%;
  overflow: hidden;
  padding: 2px 5px;
  border-radius: 4px;
  background: #F5F5F5;
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.full-results-price {
  text-align: right;
}

.full-results-price strong {
  color: #111111;
  font-size: 13px;
}

.full-results-price small.up {
  color: #C8312A;
}

.full-results-price small.down {
  color: #0E8A66;
}

.full-results-spark {
  display: flex;
  justify-content: flex-end;
}

.full-results-loading {
  padding: 12px 20px;
}

.full-results-skeleton {
  height: 42px;
  margin-bottom: 9px;
  border-radius: 6px;
  background: linear-gradient(90deg, #F1F1F1, #FAFAFA, #F1F1F1);
  background-size: 220% 100%;
  animation: sk 1.2s ease-in-out infinite;
}

.full-results-foot {
  min-height: 56px;
  padding: 0 20px;
  border-top: 1px solid #EDEDED;
  color: #71717A;
  font-size: 12px;
}

.full-results-pager button {
  height: 30px;
  min-width: 68px;
  padding: 0 10px;
}

.full-results-pager span {
  min-width: 58px;
  color: #3F3F46;
  font-size: 12px;
  text-align: center;
}


.history-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
  padding: 8px 10px;
  background: transparent;
  border-radius: 7px;
  color: #3F3D38;
  font-weight: 500;
  border-left: 2px solid transparent;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.history-item:hover {
  background: #EFEDE6;
  color: #111110;
}
.history-item.active {
  background: #EAF0FE;
  color: #1E3FA8;
  font-weight: 600;
  border-left-color: #2456D8;
}
.history-main {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}
.history-title {
  overflow: hidden;
  color: inherit;
  font-size: 11.5px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-sub {
  overflow: hidden;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 9.5px;
  font-weight: 500;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-del {
  background: transparent;
  border: none;
  padding: 2px 4px;
  border-radius: 3px;
  color: #B8B4A8;
  cursor: pointer;
  display: none;
  align-items: center;
  flex-shrink: 0;
}
.history-item:hover .history-del { display: inline-flex; }
.history-del:hover { background: rgba(200, 49, 42, 0.10); color: #C8312A; }

.tool-trace {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 14px;
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(36, 86, 216, 0.06), rgba(45, 125, 82, 0.05)), #F7F7F7;
}
.tool-trace-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #3F3F46;
  font-size: 12px;
  font-weight: 700;
}
.tool-call-list {
  display: grid;
  gap: 7px;
}
.tool-call {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 8px;
  align-items: flex-start;
}
.tool-call-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: #FFFFFF;
  color: #2456D8;
  font-family: "IBM Plex Mono", monospace;
  font-size: 11px;
  font-weight: 700;
}
.tool-call-main {
  min-width: 0;
}
.tool-call-name {
  color: #111111;
  font-size: 12.5px;
  font-weight: 700;
  line-height: 1.35;
}
.tool-call-summary {
  margin-top: 2px;
  color: #71717A;
  font-size: 12px;
  line-height: 1.5;
}
.tool-call.pending .tool-call-name {
  color: #2456D8;
}
.tool-call.pending .tool-call-index {
  background: transparent;
  color: #2456D8;
}
.tool-dots::after {
  content: '';
  display: inline-block;
  width: 1em;
  text-align: left;
  animation: tool-dots 1.2s steps(4, end) infinite;
}
@keyframes tool-dots {
  0%   { content: ''; }
  25%  { content: '.'; }
  50%  { content: '..'; }
  75%  { content: '...'; }
  100% { content: ''; }
}

.risk-note {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
  color: #71717A;
  font-size: 11px;
  line-height: 1.5;
}

@media (max-width: 1100px) {
  .chat-workbench {
    grid-template-columns: 210px minmax(0, 1fr) 260px;
  }
}

@media (max-width: 900px) {
  .chat-workbench {
    grid-template-columns: 210px minmax(0, 1fr);
  }
  .chat-workbench > :last-child {
    display: none;
  }
}

@media (max-width: 768px) {
  .chat-workbench {
    height: calc(100vh - 84px);
    min-height: calc(100vh - 84px);
    grid-template-columns: 1fr;
  }
  .chat-workbench > :first-child {
    display: none;
  }
  .starter-grid {
    grid-template-columns: 1fr;
  }
  .user-bubble {
    max-width: 92%;
  }
  .condition-intro,
  .condition-list,
  .agent-answer-panel,
  .screening-card,
  .error-card {
    margin-left: 0;
  }
  .assistant-row {
    gap: 8px;
  }
  .screening-row {
    grid-template-columns: 28px 1fr 52px;
  }
  .screening-row .sk-bar:nth-child(n + 4) {
    display: none;
  }
  .result-preview {
    margin-left: 0;
  }
  .result-preview-row {
    grid-template-areas:
      "rank stock price"
      ". facts facts";
    grid-template-columns: 24px minmax(0, 1fr) 74px;
    gap: 8px;
    padding: 10px 12px;
  }
  .result-rank {
    grid-area: rank;
  }
  .result-stock {
    grid-area: stock;
  }
  .result-industry,
  .result-trend {
    display: none;
  }
  .result-facts {
    grid-area: facts;
  }
  .result-price {
    grid-area: price;
  }
  .full-results-overlay {
    padding: 10px;
  }
  .full-results-modal {
    width: calc(100vw - 20px);
    height: calc(100vh - 20px);
  }
  .full-results-head,
  .full-results-toolbar,
  .full-results-foot {
    align-items: flex-start;
    flex-direction: column;
  }
  .full-results-actions,
  .full-results-page-sizes,
  .full-results-pager {
    width: 100%;
  }
  .full-results-secondary {
    flex: 1;
  }
  .full-results-table-wrap {
    overflow: auto;
  }
  .full-results-table-head,
  .full-results-row {
    width: 900px;
  }
  .full-results-table-body {
    height: calc(100% - 38px);
    overflow: visible;
  }
  .full-results-foot {
    justify-content: flex-start;
  }
  .full-results-pager {
    justify-content: space-between;
  }
}

/* ── AI Agent 工具调用卡片 ── */
.chat-tool-trace {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 14px;
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(36, 86, 216, 0.06), rgba(45, 125, 82, 0.05)), #F7F7F7;
}
.chat-tool-trace-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #3F3F46;
  font-size: 12px;
  font-weight: 700;
}
.chat-tool-call-list {
  display: grid;
  gap: 7px;
}
.chat-tool-call {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 8px;
  align-items: flex-start;
}
.chat-tool-call-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: #FFFFFF;
  color: #2456D8;
  font-family: "IBM Plex Mono", monospace;
  font-size: 11px;
  font-weight: 700;
}
.chat-tool-call-main {
  min-width: 0;
}
.chat-tool-call-name {
  color: #111111;
  font-size: 12.5px;
  font-weight: 700;
  line-height: 1.35;
}
.chat-tool-call-summary {
  margin-top: 2px;
  color: #71717A;
  font-size: 12px;
  line-height: 1.5;
}
.chat-tool-call.pending .chat-tool-call-name {
  color: #2456D8;
}
.chat-tool-call.pending .chat-tool-call-index {
  background: transparent;
  color: #2456D8;
}
.chat-tool-dots::after {
  content: '';
  display: inline-block;
  width: 1em;
  text-align: left;
  animation: chat-tool-dots 1.2s steps(4, end) infinite;
}
@keyframes chat-tool-dots {
  0%   { content: ''; }
  25%  { content: '.'; }
  50%  { content: '..'; }
  75%  { content: '...'; }
  100% { content: ''; }
}


.thinking-line {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #71717A;
  font-size: 12.5px;
  margin-bottom: 10px;
}

</style>

<style scoped>
.row-hover { transition: background 0.15s; }
.row-hover:hover { background: #EFEDE6; }

.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 条件 chip 出现动画（stagger 由 inline --delay 控制） */
.cond-chip {
  opacity: 0;
  transform: translateY(4px);
  animation: chip-pop 0.32s cubic-bezier(0.4, 0, 0.2, 1) forwards;
  animation-delay: var(--delay, 0ms);
}
@keyframes chip-pop {
  to { opacity: 1; transform: translateY(0); }
}

/* 三点流动 */
.dot-flow {
  display: inline-flex;
  gap: 3px;
  align-items: center;
  margin-left: 2px;
}
.dot-flow i {
  width: 4px; height: 4px;
  background: var(--c, #2456D8);
  border-radius: 50%;
  animation: dot-bob 1s infinite ease-in-out;
}
.dot-flow i:nth-child(2) { animation-delay: 0.15s; }
.dot-flow i:nth-child(3) { animation-delay: 0.30s; }
@keyframes dot-bob {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
}

/* 思考预览的等宽光标 */
.caret-mono {
  display: inline-block;
  width: 5px;
  height: 12px;
  margin-left: 1px;
  background: #B8B4A8;
  vertical-align: middle;
  animation: caret-blink 1s steps(2) infinite;
}
@keyframes caret-blink { 50% { opacity: 0; } }

/* skeleton 行（与全局 .sk 同样的 shimmer） */
.sk-bar {
  background: linear-gradient(90deg, rgba(14,14,12,0.05) 25%, rgba(14,14,12,0.10) 37%, rgba(14,14,12,0.05) 63%);
  background-size: 400% 100%;
  animation: sk-shimmer 1.4s ease-in-out infinite;
}
@keyframes sk-shimmer {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}


/* Ported from the user's AI workspace: two-pane chat shell + docked composer. */
.ai-page {
  display: flex;
  position: fixed; top: 60px; left: 0; right: 0; bottom: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  
  background: #FFFFFF;
}

.ai-shell {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.history-panel {
  display: flex;
  width: 260px;
  min-width: 0;
  min-height: 0;
  flex: 0 0 260px;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #EDEDED;
  background: #F7F7F7;
}

.history-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 14px 12px;
}

.history-head-lead {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.history-title {
  margin: 0;
  color: #111111;
  font-size: 14px;
  font-weight: 700;
}

.history-new-btn {
  min-height: 30px;
  padding: 0 12px;
  border: 1px solid #D8D8D8;
  border-radius: 999px;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
}

.history-new-btn:hover {
  border-color: #B8B8B8;
  background: #F5F5F5;
  color: #111111;
}

.history-panel-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: 6px 8px 12px;
}

.history-empty {
  display: flex;
  min-height: 96px;
  align-items: center;
  justify-content: center;
  padding: 16px;
  color: #71717A;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

.history-group-label {
  margin: 12px 0 5px;
  padding: 0 10px;
  color: #A1A1AA;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 1px;
}

.session-entry {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px;
  align-items: center;
  padding: 0 2px;
  border-radius: 10px;
  transition: background 0.18s;
}

.session-entry:hover,
.session-entry.active {
  background: #EFEDE6;
}

.session-entry.active {
  box-shadow: inset 2px 0 0 #111111;
}

.session-item {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.session-item:disabled {
  cursor: wait;
  opacity: 0.6;
}

.session-item-top {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.session-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: #111111;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  overflow: hidden;
  max-width: 100%;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 9.5px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-delete {
  display: inline-flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  margin-right: 4px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #A1A1AA;
  cursor: pointer;
  opacity: 0;
  transition: background 0.18s, color 0.18s, opacity 0.18s;
}

.session-entry:hover .session-delete,
.session-entry:focus-within .session-delete {
  opacity: 1;
}

.session-delete:hover {
  background: rgba(200, 49, 42, 0.10);
  color: #C8312A;
}

.history-clear-button {
  margin: 10px 8px 0;
  padding: 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #71717A;
  cursor: pointer;
  font-size: 11px;
}

.history-clear-button:hover {
  background: #EFEDE6;
  color: #111111;
}

.main-panel {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1 1 auto;
  flex-direction: column;
  background: #FFFFFF;
}

.main-panel.home {
  justify-content: center;
}

.home-stage {
  display: flex;
  width: 100%;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 18px;
}

.home-hero-copy {
  display: flex;
  width: min(760px, 100%);
  flex-direction: column;
  align-items: center;
  margin-bottom: 18px;
  text-align: center;
}

.home-eyebrow {
  margin: 0 0 10px;
  padding: 6px 12px;
  border: 1px solid #EDEDED;
  border-radius: 999px;
  background: #F7F7F7;
  color: #111111;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1px;
}

.home-heading {
  margin: 0;
  color: #111111;
  font-size: clamp(30px, 4vw, 44px);
  font-weight: 700;
  line-height: 1.1;
}

.home-subtitle {
  max-width: 640px;
  margin: 14px 0 0;
  color: #71717A;
  font-size: 14px;
  line-height: 1.7;
}

.home-prompt-grid {
  display: grid;
  width: min(760px, 100%);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.home-prompt-card {
  display: grid;
  align-content: center;
  padding: 10px 14px;
  border: 1px solid #EDEDED;
  border-radius: 12px;
  background: #FFFFFF;
  color: #111111;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.18s;
}

.home-prompt-card:hover:not(:disabled) {
  border-color: #A1A1AA;
}

.home-prompt-card:disabled {
  cursor: wait;
  opacity: 0.55;
}

.home-prompt-kicker {
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 1px;
}

.home-prompt-title {
  color: #111111;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.45;
}

.composer {
  display: flex;
  width: 100%;
  flex-direction: column;
  padding: 10px 10px 8px 16px;
  border: 1px solid #EDEDED;
  border-radius: 24px;
  background: #FFFFFF;
  box-shadow: 0 10px 30px rgba(14, 14, 12, 0.08);
  transition: border-color 0.18s, box-shadow 0.18s;
}

.composer:focus-within {
  border-color: #111111;
  box-shadow: 0 0 0 3px rgba(17, 17, 17, 0.08), 0 10px 30px rgba(14, 14, 12, 0.08);
}

.composer--home,
.composer--thread {
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
}

.composer-input {
  width: 100%;
  min-height: 30px;
  height: auto;
  padding: 8px 4px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #111111;
  font-size: 15px;
  line-height: 1.6;
  resize: none;
}

.composer-input::placeholder {
  color: #A1A1AA;
}

.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 3px;
}

.composer-modes {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.mode-chip {
  display: inline-flex;
  max-width: 280px;
  height: 30px;
  align-items: center;
  overflow: hidden;
  padding: 0 12px;
  border: 1px solid #EDEDED;
  border-radius: 999px;
  background: #F7F7F7;
  color: #3F3F46;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mode-chip:hover:not(:disabled) {
  background: #FFFFFF;
  color: #111111;
}

.send-icon-btn {
  display: inline-flex;
  width: 36px;
  height: 36px;
  flex: none;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: #111111;
  color: #FFFFFF;
  cursor: pointer;
  transition: background 0.18s, opacity 0.18s, transform 0.18s;
}

.send-icon-btn.stop {
  background: #3F3D38;
}

.send-icon-btn:hover:not(:disabled) {
  background: #000000;
}

.send-icon-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.thread-shell {
  display: flex;
  height: 100%;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 32px 24px 16px;
  scroll-behavior: smooth;
}

.chat-scroll:not(.has-thread) {
  display: block;
}

.chat-thread {
  display: flex;
  width: 100%;
  max-width: 820px;
  margin: 0 auto;
  flex-direction: column;
  gap: 30px;
}

.msg-pair {
  display: grid;
  gap: 18px;
  animation: msg-fade-in 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes msg-fade-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
}

.msg.user {
  align-items: flex-end;
}

.msg.assistant {
  align-items: stretch;
}

.msg-content {
  min-width: 0;
  color: #111111;
  font-size: 14px;
  line-height: 1.75;
}

.msg.user .msg-content {
  max-width: 82%;
  padding: 10px 16px;
  border-radius: 20px;
  background: #F7F7F7;
  color: #111111;
  line-height: 1.6;
}

.assistant-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: #111111;
  font-size: 12px;
  font-weight: 800;
}

.assistant-head em {
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
}

.assistant-avatar {
  display: inline-grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 8px;
  background: #111111;
  color: #FFFFFF;
  font-size: 11px;
  font-weight: 800;
}

.agent-answer-panel {
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
  color: #2F3137;
  font-size: 14px;
}

.condition-block {
  display: grid;
  gap: 8px;
  margin: 4px 0 12px;
}

.condition-intro,
.condition-list,
.screening-card,
.error-card,
.result-preview {
  margin-left: 0;
}

.condition-intro {
  color: #71717A;
  font-size: 12px;
  line-height: 1.55;
}

.condition-list {
  gap: 7px;
}


.thinking-placeholder {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-radius: 12px;
  background: #F7F7F7;
  color: #71717A;
  font-size: 13px;
}

.thinking-preview {
  max-height: 120px;
  margin: 8px 0 0;
  overflow: hidden;
  padding: 8px 10px;
  border-radius: 8px;
  background: #F7F7F7;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10.5px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.error-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(200, 49, 42, 0.10);
  color: #C8312A;
  font-size: 12px;
}


.composer-dock {
  flex-shrink: 0;
  padding: 12px 24px 18px;
  background: linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,0.94) 28%, #FFFFFF 62%);
}


.composer-status {
  overflow: hidden;
  color: #A1A1AA;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-status.warning {
  color: #987400;
}

.status-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 auto 16px;
  width: min(820px, 100%);
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 12px;
}

.warning-banner {
  background: #FFFBEB;
  color: #987400;
}

.status-banner span {
  display: flex;
  min-width: 0;
  flex: 1;
  gap: 6px;
  align-items: baseline;
}

.status-banner em {
  overflow: hidden;
  color: #71717A;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid #EDEDED;
  border-radius: 999px;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
}

@media (max-width: 900px) {
  .history-panel {
    display: none;
  }

  .ai-page {
    height: calc(100vh - 84px);
    min-height: calc(100vh - 84px);
  }

  .chat-scroll {
    padding: 24px 16px 12px;
  }

  .composer-dock {
    padding: 10px 16px 14px;
  }

}

@media (max-width: 680px) {
  .home-stage {
    justify-content: flex-start;
    padding: 48px 14px 18px;
  }

  .home-heading {
    font-size: 24px;
  }

  .home-subtitle {
    font-size: 13px;
  }

  .home-prompt-grid {
    grid-template-columns: 1fr;
  }

  .composer {
    border-radius: 20px;
    padding: 8px 8px 6px 14px;
  }

  .mode-chip {
    max-width: 180px;
    padding: 0 10px;
  }

  .msg.user .msg-content {
    max-width: 92%;
  }
}
</style>
