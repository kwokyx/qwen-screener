<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import EmptyState from '../components/EmptyState.vue'
import { A2 } from '../shared/theme.js'
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
const stream = useNlStream(history, { onResult: loadSparks })
const {
  phase, lastQuery, thinkingBuf, parsedConditions, screenMeta, result, agentAnswer, agentPlan, toolTrace, toolCalls, errorMsg,
  thread, liveTurn,
  tStart, tParsed, tDone, isStreaming,
  send: streamSend, stop, restoreFromHistory: streamRestore, clearThread,
} = stream

const chatScroll = ref(null)
const canSubmit = computed(() => Boolean(input.value.trim()) && !isStreaming.value)

const presetPrompts = [
  '低估值高分红的银行股',
  'ROE 大于 15 且最新季度净利润同比正增长的成长股',
  '半导体行业市值 500 亿以上的龙头',
  '股息率超过 5% 的大蓝筹',
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
const turnResultItems = (turn) => (turn?.result?.items || []).slice(0, 6)
const turnAnswerLines = (turn) => (turn?.agentAnswer || '').split('\n').filter(Boolean)
const turnThinkingPreview = (turn) => {
  const s = turn?.thinkingBuf || ''
  return s.length <= 200 ? s : '…' + s.slice(-200)
}
const isDesignTurn = (turn) => turn?.agentPlan?.tool === 'strategy_design'
const isTextOnlyTurn = (turn) => textOnlyTools.includes(turn?.agentPlan?.tool) && !turn?.result
const turnAgentTitle = (turn) => turn?.agentPlan?.tool_label || 'Agent 结论'
const turnToolLabel = (turn) => turn?.agentPlan?.tool_label || (turn?.result ? '股票筛选' : '待判断')
function agentSourceLabel(plan, aiRuntime = null) {
  if (aiRuntime?.source === 'ai_agent' || aiRuntime?.used === true) return 'AI Agent'
  if (aiRuntime?.source === 'local_fallback' || aiRuntime?.fallback) return '本地规则兜底'
  if (aiRuntime?.source === 'local_rules' || aiRuntime?.configured === false) return '本地规则'
  if (aiRuntime?.label) return aiRuntime.label
  if (plan?.ai_configured) return '本地规则兜底'
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
function fmtRuntimeMs(ms) {
  const n = Number(ms || 0)
  if (n >= 1000) return `${(n / 1000).toFixed(1)}s`
  return `${Math.max(0, Math.round(n))}ms`
}
function fallbackReasonText(reason) {
  if (!reason) return ''
  if (reason === 'local_fast_path') return '本地快速路径'
  if (reason === 'local_rules') return '本地规则'
  const text = String(reason)
  return text.length > 42 ? `${text.slice(0, 42)}…` : text
}
const runtimeRows = computed(() => {
  const turn = latestTurn.value
  const meta = turn?.screenMeta || screenMeta.value || {}
  const timings = meta.timings || meta
  const hasTiming = (
    timings.planning_ms != null ||
    timings.model_ms != null ||
    timings.tool_ms != null ||
    timings.fallback_reason != null
  )
  if (!hasTiming) return []
  const tool = meta.tool || turn?.agentPlan?.tool || agentPlan.value?.tool
  const modelMs = Number(timings.model_ms || 0)
  const toolMs = Number(timings.tool_ms || 0)
  const usedModel = meta.ai_status?.used === true || meta.ai_status?.source === 'ai_agent'
  const reason = fallbackReasonText(timings.fallback_reason)
  const modelAttempted = !usedModel && modelMs > 0
  const rows = [
    {
      label: '工具选择',
      value: usedModel
        ? `ReAct 模型 ${fmtRuntimeMs(modelMs)}`
        : (modelAttempted ? `模型未完成 ${fmtRuntimeMs(modelMs)}` : `本地判断 ${fmtRuntimeMs(timings.planning_ms)}`),
      state: usedModel ? 'model' : (modelAttempted ? 'skip' : 'local'),
    },
  ]
  if (tool === 'stock_screen' || tool === 'strategy_select') {
    rows.push({
      label: '本地工具',
      value: toolMs > 0 ? `执行 ${fmtRuntimeMs(toolMs)}` : (phase.value === 'screening' ? '执行中…' : '0ms'),
      state: phase.value === 'screening' ? 'running' : 'local',
    })
  } else if (tool === 'sort_results' || tool === 'paginate_results') {
    rows.push({
      label: '本地结果操作',
      value: toolMs > 0 ? `执行 ${fmtRuntimeMs(toolMs)}` : '0ms',
      state: 'local',
    })
  } else {
    rows.push({ label: '本地工具', value: '未执行筛选', state: 'skip' })
  }
  if (reason) rows.push({ label: '兜底原因', value: reason, state: 'skip' })
  return rows
})
const aiStatusLine = computed(() => {
  if (!aiStatus.lastChecked) return 'AI 检测中…'
  if (aiStatus.pending) return 'AI 检测中 · 本地规则可用'
  if (aiStatus.stale) return 'AI 状态刷新中 · 使用上次结果'
  if (!aiStatus.configured && aiStatus.reason && !aiStatus.reason.includes('未配置')) {
    return 'AI 探测失败 · 本地规则兜底'
  }
  if (!aiStatus.configured) return 'AI 未配置 · 本地规则'
  if (!aiStatus.isUp) return `${aiStatus.backend || 'AI'} 不可用 · 本地规则兜底`
  return `AI Agent 就绪 · ${[aiStatus.backend, aiStatus.model].filter(Boolean).join(' / ')}`
})
const agentAnswerLines = computed(() => (agentAnswer.value || '').split('\n').filter(Boolean))
const agentAnswerTitle = computed(() => agentPlan.value?.tool_label || 'Agent 结论')
const agentToolLabel = computed(() => agentPlan.value?.tool_label || (result.value ? '股票筛选' : '待判断'))
const conditionIntro = computed(() => {
  if (agentPlan.value?.tool === 'strategy_design') return '建议量化条件'
  if (agentPlan.value?.tool === 'explain_result') return '上一轮条件'
  return result.value ? `筛选条件 · 命中 ${result.value.total} 只` : '识别条件'
})
const resultTitle = computed(() => agentPlan.value?.tool === 'strategy_select' ? '策略选股结果' : '筛选结果')
function historyBadge(c) {
  if (c.status) return c.status
  const tool = c.agentPlan?.tool
  if (tool === 'strategy_design') return '策略'
  if (tool === 'ask_clarification') return '追问'
  if (tool === 'explain_result') return '解释'
  if (tool === 'stock_detail') return '详情'
  return `${c.total} 只`
}
function historyTitle(c) {
  return c.title || c.query || '新建对话'
}
function historyMeta(c) {
  const ts = c.updatedAt || c.ts
  return [ts ? fmtRelTime(ts) : '', `${c.turnCount || 1}轮`].filter(Boolean).join(' · ')
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

const toolCallRows = computed(() => latestTurn.value?.toolCalls || toolCalls.value || [])
const toolStatusLabel = (status) => ({
  pending: '等待',
  running: '执行中',
  done: '完成',
  skipped: '跳过',
  failed: '失败',
}[status] || status || '完成')
const toolStatusColor = (status) => ({
  pending: A2.textDim,
  running: A2.qwen,
  done: A2.up,
  skipped: A2.textMuted,
  failed: A2.down,
}[status] || A2.textDim)
function toolParamText(call) {
  const result = call?.result || {}
  if (call?.name === 'stock_screen' && result.total != null) return `命中 ${result.total} 只`
  if (call?.name === 'strategy_select' && result.total != null) return `命中 ${result.total} 只`
  if (call?.name === 'stock_detail' && result.code) return `目标 ${result.name || result.code}`
  if (call?.name === 'condition_parser') return call.message || '已生成筛选条件'
  if (call?.name === 'result_sort') return call.message || '已调整结果范围'
  if (call?.message) return call.message.length > 42 ? `${call.message.slice(0, 42)}…` : call.message
  return ''
}

function detailTargetFromToolCalls(calls = []) {
  return (calls || []).find((call) => call?.name === 'stock_detail' && call?.result?.code)?.result || null
}

function turnDetailTarget(turn) {
  return detailTargetFromToolCalls(turn?.toolCalls)
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
  const plan = turn?.agentPlan || agentPlan.value
  if (plan?.tool === 'strategy_select') {
    router.push('/strategy')
    return
  }
  const turnResult = turn?.result || result.value || null
  const sortBy = turn?.screenMeta?.sort_by || plan?.sort_by || screenMeta.value?.sort_by || 'score'
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
  history.newSession()
}

function retryTurn(turn) {
  if (!turn?.query || isStreaming.value) return
  input.value = turn.query
  send()
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

// 从其他页面跳转携带 ?q=xxx 时自动发送
onMounted(() => {
  const sessionId = route.query.session
  if (sessionId && typeof sessionId === 'string') {
    streamRestore(sessionId)
    router.replace({ path: '/chat' })
    return
  }
  const q = route.query.q
  if (q && typeof q === 'string') {
    input.value = q
    send()
    // 用过即清，刷新不重发
    router.replace({ path: '/chat' })
  }
})

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
    <div class="chat-workbench">
      <!-- Sidebar -->
      <div :style="{ background: A2.surface, padding: '14px', fontSize: '12px', overflow: 'auto', borderRight: `1px solid ${A2.borderHair}` }">
        <button :style="{ width: '100%', padding: '10px 12px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', borderRadius: '8px', marginBottom: '16px', boxShadow: '0 2px 8px rgba(14,14,12,0.10)' }"
                @click="newSession">
          <Icon name="plus" :size="12" /> 新建对话
        </button>

        <div v-if="!history.items.length" :style="{ fontSize: '11px', color: A2.textMuted, padding: '10px', lineHeight: 1.55, textAlign: 'center', border: `1px dashed ${A2.borderHair}`, borderRadius: '6px', background: A2.bg }">
          在中间输入目标开始筛选
        </div>

        <!-- 分组：今天 / 昨天 / 本周 / 更早 -->
        <template v-for="group in [
          { key: 'today', label: '今天', list: history.grouped.today },
          { key: 'yesterday', label: '昨天', list: history.grouped.yesterday },
          { key: 'thisWeek', label: '本周', list: history.grouped.thisWeek },
          { key: 'earlier', label: '更早', list: history.grouped.earlier },
        ]" :key="group.key">
          <div v-if="group.list.length" :style="{ fontSize: '10px', color: A2.textDim, fontWeight: 700, letterSpacing: '1.2px', marginBottom: '6px', marginTop: '12px', paddingLeft: '4px' }">{{ group.label }}</div>
          <div v-for="c in group.list" :key="c.id"
               class="history-item"
               :class="{ active: c.id === history.activeId }"
               @click="restoreFromHistory(c.id)"
               :title="isStreaming ? '当前对话进行中，请先停止' : historyTitle(c)"
               :style="{ padding: '8px 10px', borderRadius: '7px', marginBottom: '3px', display: 'flex', alignItems: 'center', gap: '8px', cursor: isStreaming ? 'wait' : 'pointer' }">
            <span class="history-main">
              <span class="history-title">{{ historyTitle(c) }}</span>
              <span class="history-sub">{{ historyMeta(c) }}</span>
            </span>
            <span class="history-badge">{{ historyBadge(c) }}</span>
            <button class="history-del" @click="deleteHistory(c.id, $event)" title="删除">
              <Icon name="x" :size="10" />
            </button>
          </div>
        </template>

        <button v-if="history.items.length" @click="history.clear()"
                :style="{ marginTop: '12px', width: '100%', padding: '6px', background: 'transparent', border: 'none', color: A2.textMuted, fontSize: '10.5px', cursor: 'pointer', borderRadius: '5px' }">
          清空全部历史 ({{ history.items.length }})
        </button>

        <div :style="{ marginTop: '22px', padding: '12px', background: A2.bgDeep, borderRadius: '8px' }">
          <div :style="{ fontSize: '11px', fontWeight: 700, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '5px' }">
            <Icon name="lightbulb" :size="11" :color="A2.amber" /> 推荐提问
          </div>
          <div v-for="t in presetPrompts" :key="t"
               @click="!isStreaming && pickPreset(t)"
               :style="{ fontSize: '11px', padding: '6px 0', color: A2.textSub, cursor: isStreaming ? 'wait' : 'pointer', lineHeight: 1.5, opacity: isStreaming ? 0.5 : 1 }">· {{ t }}</div>
        </div>
      </div>

      <!-- Main chat -->
      <div :style="{ background: A2.bg, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }">
        <!-- Input -->
        <div :style="{ order: 2, borderTop: `1px solid ${A2.borderHair}`, padding: '12px 16px', background: A2.surface }">
          <div :style="{ border: `1px solid ${A2.borderHair}`, padding: '10px 12px', background: A2.surfaceElev, borderRadius: '8px', boxShadow: A2.shadowMd }">
            <textarea v-model="input"
                      @keydown.enter.exact.prevent="send"
                      :disabled="isStreaming"
                      placeholder="例如：找出 PE 低于 15、ROE > 15%、最新季度净利润同比 > 20% 的消费股…"
                      :style="{ width: '100%', height: '36px', border: 'none', outline: 'none', fontSize: '13px', fontFamily: 'IBM Plex Sans, Noto Sans SC, sans-serif', resize: 'none', background: 'transparent', opacity: isStreaming ? 0.6 : 1 }" />
            <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', paddingTop: '8px', borderTop: `1px solid ${A2.borderHair}` }">
              <span v-if="!aiStatus.isUp" :style="{ fontSize: '10px', color: A2.amber, display: 'flex', alignItems: 'center', gap: '4px' }">
                <span :style="{ width: '6px', height: '6px', borderRadius: '50%', background: A2.amber }" />
                {{ aiStatusLine }}
              </span>
              <span v-else :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">
                {{ phase === 'thinking' ? '选择下一步中…' : phase === 'screening' ? '本地工具执行中…' : aiStatusLine }}
              </span>
              <div style="flex:1" />
              <button v-if="isStreaming" @click="stop"
                      :style="{ padding: '7px 14px', background: '#3F3D38', color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '6px', boxShadow: '0 2px 8px rgba(14,14,12,0.12)' }">
                <Icon name="x" :size="12" /> 停止
              </button>
              <button v-else @click="send"
                      :disabled="!canSubmit"
                      :title="!aiStatus.isUp ? `AI 服务暂时不可用（${aiStatus.reason || '上游网络异常'}），将使用本地规则兜底` : ''"
                      :style="{ padding: '7px 14px', background: canSubmit ? A2.qwenGrad : '#B8B4A8', color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: canSubmit ? 'pointer' : 'not-allowed', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '6px', boxShadow: '0 2px 8px rgba(14,14,12,0.12)', opacity: canSubmit ? 1 : 0.7 }">
                发送 <Icon name="send" :size="12" />
              </button>
            </div>
          </div>
        </div>

        <div ref="chatScroll" class="chat-scroll" :class="{ 'has-thread': hasConversation }" :style="{ order: 1, flex: 1, overflow: 'auto', padding: '16px 24px', minHeight: 0 }">
          <!-- AI 离线时的状态条 -->
          <div v-if="!aiStatus.isUp" :style="{ marginBottom: '16px', padding: '10px 14px', background: A2.amberSoft, color: A2.amber, borderRadius: '8px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '10px' }">
            <Icon name="alert" :size="13" />
            <span style="flex:1">
              <strong>本地规则兜底</strong>
              <span :style="{ color: A2.textMuted, marginLeft: '6px' }">{{ aiStatus.reason || 'AI 服务暂时不可达' }}</span>
            </span>
            <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="aiStatus.recheck">
              <Icon name="refresh" :size="11" /> 重新检测
            </button>
          </div>

          <!-- 起始引导 -->
          <div v-if="!hasConversation" class="starter-panel">
            <div :style="{ display: 'grid', gridTemplateColumns: '40px 1fr', gap: '12px', alignItems: 'center' }">
              <div :style="{ display: 'grid', placeItems: 'center', width: '40px', height: '40px', borderRadius: '8px', background: A2.qwenSoft, color: A2.qwen }">
                <Icon name="sparkle" :size="20" />
              </div>
              <div>
                <div :style="{ fontSize: '14px', fontWeight: 700, color: A2.text, marginBottom: '3px' }">智能筛选</div>
                <div :style="{ fontSize: '12px', color: A2.textMuted }">输入目标，返回条件、追问或股票池。</div>
              </div>
            </div>
            <div class="starter-grid">
              <button v-for="t in presetPrompts" :key="t" type="button" @click="!isStreaming && pickPreset(t)">
                {{ t }}
              </button>
            </div>
          </div>

          <div v-if="hasConversation" class="conversation-list">
            <article v-for="turn in conversationTurns" :key="turn.id" class="conversation-turn">
              <div class="user-message">
                <div class="user-bubble">{{ turn.query }}</div>
              </div>

              <div v-if="turn.phase === 'thinking'" class="assistant-row">
                <div class="assistant-avatar">千</div>
                <div class="thinking-card">
                  <div class="thinking-head">
                    <Icon name="brain" :size="11" :color="A2.qwen" />
                    <span>正在选择下一步…</span>
                    <span class="dot-flow"><i></i><i></i><i></i></span>
                  </div>
                  <pre v-if="turn.thinkingBuf" class="thinking-preview">{{ turnThinkingPreview(turn) }}<span class="caret-mono" /></pre>
                </div>
              </div>

              <template v-if="turn.parsedConditions?.length">
                <div class="condition-intro">
                  <template v-if="isDesignTurn(turn)">
                    {{ turnConditionIntro(turn) }}：
                  </template>
                  <template v-else>
                    {{ turnConditionIntro(turn) }}<span v-if="turn.phase === 'screening'">，执行中…</span>：
                  </template>
                </div>
                <div class="condition-list">
                  <div v-for="(c, i) in turn.parsedConditions" :key="i"
                       class="cond-chip"
                       :style="{ '--delay': (i * 60) + 'ms' }">
                    <span>{{ fmtCond(c) }}</span>
                  </div>
                </div>
              </template>

              <div v-if="turnAnswerLines(turn).length" class="agent-answer-panel" :class="{ compact: isTextOnlyTurn(turn) }">
                <div class="agent-answer-title">
                  <span>{{ turnAgentTitle(turn) }}</span>
                  <em>{{ turnSourceLabel(turn) }}</em>
                </div>
                <div v-for="(line, i) in turnAnswerLines(turn)" :key="i" class="agent-answer-line">
                  {{ line }}
                </div>
                <button
                  v-if="turnDetailTarget(turn)"
                  type="button"
                  class="agent-detail-button"
                  @click="openDetailTarget(turnDetailTarget(turn))"
                >
                  打开详情 <Icon name="arrowRight" :size="12" />
                </button>
              </div>

              <div v-if="turn.phase === 'screening'" class="screening-card">
                <div class="screening-head">
                  <span class="dot-flow" :style="{ '--c': A2.qwen }"><i></i><i></i><i></i></span>
                  {{ turnToolLabel(turn) }}执行中…
                </div>
                <div v-for="n in 4" :key="n" class="screening-row">
                  <div class="sk-bar" />
                  <div class="sk-bar wide" />
                  <div class="sk-bar" />
                  <div class="sk-bar" />
                  <div class="sk-bar" />
                </div>
              </div>

              <div v-if="turn.phase === 'error'" class="error-card">
                <Icon name="shield" :size="14" />
                <div style="flex:1">{{ turn.errorMsg }}</div>
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
                      <small :class="{ up: s.change_pct > 0, down: s.change_pct < 0 }">{{ fmtChange(s.change_pct) }}</small>
                    </span>
                    <span class="result-trend"><Sparkline :data="spark(s.code)" :width="72" :height="20" /></span>
                  </button>
                </div>
                <EmptyState v-else icon="filter" :title="emptyResultTitleFor(turn)" :subtitle="zeroResultHintFor(turn)" />
              </div>
            </article>
          </div>
        </div>
      </div>

      <!-- Right inspector：实时阶段时间轴 -->
      <div :style="{ background: A2.surface, padding: '16px', fontSize: '11px', overflow: 'auto', borderLeft: `1px solid ${A2.borderHair}` }">
        <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }">
          <Icon name="tools" :size="12" :color="A2.qwen" /> 实时执行
          <span v-if="phase !== 'idle'" :style="{ marginLeft: 'auto', fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ phase }}</span>
        </div>

        <div v-if="phase === 'idle'" :style="{ fontSize: '11px', color: A2.textMuted, lineHeight: 1.6 }">
          等待输入
        </div>

        <template v-else>
          <div v-if="runtimeRows.length" class="runtime-list">
            <div v-for="row in runtimeRows" :key="row.label" class="runtime-row" :class="row.state">
              <span>{{ row.label }}</span>
              <strong>{{ row.value }}</strong>
            </div>
          </div>

          <div v-if="toolCallRows.length" class="tool-call-list">
            <div v-for="call in toolCallRows" :key="call.id" class="tool-call-row" :style="{ '--state': toolStatusColor(call.status) }">
              <div class="tool-call-head">
                <span class="stage-dot" :class="call.status" :style="{ '--c': toolStatusColor(call.status) }"></span>
                <strong>{{ call.label || call.name }}</strong>
                <em>{{ toolStatusLabel(call.status) }}</em>
              </div>
              <div v-if="toolParamText(call)" class="tool-call-meta">{{ toolParamText(call) }}</div>
            </div>
          </div>
          <div v-else v-for="(stg, i) in stages" :key="stg.t"
               :style="{ padding: '8px 10px', borderLeft: `2px solid ${stageColor(stg.state)}`, background: A2.bgDeep, marginBottom: '5px', fontSize: '10.5px', borderRadius: '0 6px 6px 0' }">
            <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">
              <span :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
                <span class="stage-dot" :class="stg.state" :style="{ '--c': stageColor(stg.state) }"></span>
                {{ stg.t }}
              </span>
              <span :style="{ color: A2.textDim, fontWeight: 500 }">{{ stg.dur || (stg.state === 'running' ? '…' : '') }}</span>
            </div>
            <div :style="{ color: A2.textMuted, marginTop: '3px' }">{{ stg.out }}</div>
          </div>
        </template>

        <div v-if="toolTrace.length && !toolCallRows.length" :style="{ marginTop: '14px', padding: '10px 12px', background: A2.bgDeep, borderRadius: '6px', fontSize: '10.5px', color: A2.textSub, fontFamily: 'IBM Plex Mono, monospace', lineHeight: 1.6 }">
          <div :style="{ color: A2.textDim, fontSize: '9.5px', letterSpacing: '1px', marginBottom: '4px' }">工具记录</div>
          <div v-for="trace in toolTrace" :key="trace">{{ traceDisplay(trace) }}</div>
        </div>

        <div v-if="screenMeta" :style="{ marginTop: '14px', padding: '10px 12px', background: A2.bgDeep, borderRadius: '6px', fontSize: '10.5px', color: A2.textSub, fontFamily: 'IBM Plex Mono, monospace', lineHeight: 1.6 }">
          <div :style="{ color: A2.textDim, fontSize: '9.5px', letterSpacing: '1px', marginBottom: '4px' }">本轮信息</div>
          工具：{{ screenMeta.tool_label || screenMeta.tool || 'Agent' }}<br />
          状态：{{ result ? `命中 ${result.total} 只` : (isTextOnlyAgent ? '未执行筛选' : '已完成') }}<br />
          来源：{{ sourceLabel }}
        </div>

        <div class="risk-note">
          <Icon name="shield" :size="12" :color="A2.textMuted" />
          <span>仅供研究参考，不构成投资建议。</span>
        </div>
      </div>
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

.starter-panel {
  width: min(100%, 760px);
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
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
  border: 1px solid #EDEDED;
  border-radius: 8px;
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
  border: 1px solid #EDEDED;
  border-radius: 8px;
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
  border: 1px solid #EDEDED;
  border-radius: 8px;
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

.agent-answer-line + .agent-answer-line {
  margin-top: 4px;
}

.agent-detail-button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 10px;
  padding: 6px 10px;
  border: 1px solid #D8D8D8;
  border-radius: 4px;
  background: #FFFFFF;
  color: #3F3F46;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
}

.agent-detail-button:hover {
  border-color: #B8B8B8;
  background: #F5F5F5;
  color: #111111;
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

.result-price small.up {
  color: #C8312A;
}

.result-price small.down {
  color: #178A55;
}

.history-item {
  position: relative;
  background: transparent;
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
.history-badge {
  min-width: 30px;
  flex-shrink: 0;
  padding: 2px 5px;
  border-radius: 4px;
  background: rgba(14, 14, 12, 0.05);
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 9px;
  font-weight: 600;
  text-align: center;
}
.history-item.active .history-badge {
  background: rgba(36, 86, 216, 0.10);
  color: #2456D8;
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

.runtime-list {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
}

.runtime-row {
  display: grid;
  grid-template-columns: minmax(72px, auto) minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  line-height: 1.35;
}

.runtime-row span {
  color: #A1A1AA;
  font-weight: 600;
}

.runtime-row strong {
  min-width: 0;
  overflow: hidden;
  color: #2F3137;
  font-weight: 700;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-row.model { border-color: rgba(36, 86, 216, 0.22); }
.runtime-row.local { border-color: rgba(45, 125, 82, 0.22); }
.runtime-row.running { border-color: rgba(36, 86, 216, 0.32); background: rgba(36, 86, 216, 0.05); }
.runtime-row.skip { background: #F7F7F7; }

.tool-call-list {
  display: grid;
  gap: 6px;
}

.tool-call-row {
  padding: 9px 10px;
  border-left: 2px solid var(--state);
  border-radius: 0 6px 6px 0;
  background: #F7F7F7;
}

.tool-call-head {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #111111;
  font-size: 10.8px;
  font-weight: 600;
}

.tool-call-head strong {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-call-head em {
  flex-shrink: 0;
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 9.5px;
  font-style: normal;
  font-weight: 600;
}

.tool-call-meta {
  margin-top: 4px;
  color: #71717A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  line-height: 1.45;
  word-break: break-word;
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
}
</style>

<style scoped>
.row-hover { transition: background 0.15s; }
.row-hover:hover { background: #EFEDE6; }

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

/* inspector 阶段圆点 */
.stage-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--c);
  display: inline-block;
}
.stage-dot.running { animation: pulse-ring 1.2s infinite; }
@keyframes pulse-ring {
  0%   { box-shadow: 0 0 0 0 rgba(36,86,216,0.45); }
  70%  { box-shadow: 0 0 0 6px rgba(36,86,216,0); }
  100% { box-shadow: 0 0 0 0 rgba(36,86,216,0); }
}
</style>
