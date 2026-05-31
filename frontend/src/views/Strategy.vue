<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NNumberAnimation,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSkeleton,
  NSpace,
  NTag,
} from 'naive-ui'
import Shell from '../components/Shell.vue'
import { screen as screenStocks } from '../api/screener'
import { getStrategyTemplates, getStrategyTools, runStrategyAgent, selectStrategy } from '../api/strategy'
import { useAiStatusStore } from '../stores/aiStatus'

const router = useRouter()
const aiStatus = useAiStatusStore()

const templates = ref([])
const tools = ref([])
const activeId = ref('')
const result = ref(null)
const agentResult = ref(null)
const structuredResult = ref(null)
const agentQuery = ref('低估值高分红的银行股')
const loading = ref(false)
const agentLoading = ref(false)
const structuredLoading = ref(false)
const errorMsg = ref('')
const agentError = ref('')
const structuredError = ref('')
let structuredConditionId = 2
const structuredConditions = ref([
  { id: 1, field: 'pe', op: 'lt', value: 20, value2: null },
  { id: 2, field: 'roe', op: 'gt', value: 10, value2: null },
])
const structuredLogic = ref('AND')
const structuredSortBy = ref('market_cap')
const structuredSortDesc = ref(true)

const activeTemplate = computed(() => templates.value.find((item) => item.id === activeId.value))
const rows = computed(() => {
  const screen = agentResult.value?.screen_result || structuredResult.value
  if (screen) {
    const labels = agentResult.value?.plan?.condition_labels?.length
      ? agentResult.value.plan.condition_labels
      : structuredConditionLabels.value
    return mapScreenRows(screen.items || [], labels)
  }
  return agentResult.value?.strategy_result?.items || result.value?.items || []
})
const displayTotal = computed(() => agentResult.value?.screen_result?.total ?? structuredResult.value?.total ?? agentResult.value?.strategy_result?.total ?? result.value?.total ?? 0)
const displayTradeDate = computed(() => agentResult.value?.screen_result?.items?.[0]?.trade_date
  || structuredResult.value?.items?.[0]?.trade_date
  || agentResult.value?.strategy_result?.trade_date
  || result.value?.trade_date
  || '-')
const displayTitle = computed(() => {
  if (agentResult.value) return `Agent：${agentResult.value.plan?.tool_label || '智能选股'}`
  if (structuredResult.value) return '结构化条件筛选'
  return activeTemplate.value?.name || '策略'
})
const stockScreenTool = computed(() => tools.value.find((item) => item.id === 'stock_screen'))
const strategyTool = computed(() => tools.value.find((item) => item.id === 'strategy_select'))
const activeTool = computed(() => {
  if (agentResult.value?.plan?.tool) return tools.value.find((item) => item.id === agentResult.value.plan.tool)
  if (structuredResult.value) return stockScreenTool.value
  return strategyTool.value || tools.value[0]
})
const visibleFields = computed(() => stockScreenTool.value?.fields?.slice(0, 9) || [])
const activeToolNotes = computed(() => activeTool.value?.data_notes || [])
const fieldLabelMap = computed(() => Object.fromEntries((stockScreenTool.value?.fields || []).map((field) => [field.key, field.label])))
const structuredFieldOptions = computed(() => (stockScreenTool.value?.fields || []).map((field) => ({
  label: field.label,
  value: field.key,
})))
const structuredSortOptions = computed(() => [
  { label: '默认排序', value: '' },
  ...(stockScreenTool.value?.fields || [])
    .filter((field) => field.data_type === 'number')
    .map((field) => ({ label: field.label, value: field.key })),
])
const operatorLabels = {
  gt: '大于',
  gte: '大于等于',
  lt: '小于',
  lte: '小于等于',
  eq: '等于',
  between: '介于',
  in: '包含任一',
}
const structuredConditionLabels = computed(() => structuredConditions.value.map(formatStructuredCondition))
const tableLoading = computed(() => loading.value || agentLoading.value || structuredLoading.value)
const agentConditionList = computed(() => {
  if (!agentResult.value) return []
  const labels = agentResult.value.plan?.condition_labels || []
  if (labels.length) return labels
  if (agentResult.value.plan?.tool === 'strategy_select') {
    return activeTemplate.value?.rules || []
  }
  return ['未指定细分条件，使用默认股票池约束']
})
const agentSortText = computed(() => {
  const plan = agentResult.value?.plan
  if (!plan?.sort_by) return '默认排序'
  const label = fieldLabelMap.value[plan.sort_by] || plan.sort_by
  return `${label}${plan.sort_desc ? '从高到低' : '从低到高'}`
})
const agentTopHits = computed(() => rows.value.slice(0, 5).map((item) => ({
  code: item.code,
  name: item.name || item.code,
  industry: item.industry || '-',
  close: item.close,
  change_pct: item.change_pct,
})))
const agentRiskNotes = computed(() => {
  if (!agentResult.value) return []
  const notes = [
    ...(agentResult.value.warnings || []),
    ...activeToolNotes.value,
    '选股结果只表示当前数据命中条件，不构成买卖建议。',
  ]
  return [...new Set(notes)]
})
const agentToolTrace = computed(() => agentResult.value?.tool_trace || [])

const summary = computed(() => {
  const list = rows.value
  const changeItems = list.filter((item) => typeof item.change_pct === 'number')
  const up = changeItems.filter((item) => item.change_pct > 0).length
  const scoreItems = list.filter((item) => typeof item.score === 'number')
  const avgScore = scoreItems.length ? scoreItems.reduce((sum, item) => sum + item.score, 0) / scoreItems.length : null
  return [
    { label: '命中股票', value: displayTotal.value, suffix: '只' },
    { label: '当前显示', value: list.length, suffix: '只' },
    { label: '上涨占比', value: changeItems.length ? Math.round(up / changeItems.length * 100) : null, suffix: '%' },
    { label: '平均得分', value: avgScore == null ? null : Number(avgScore.toFixed(1)), suffix: '' },
  ]
})

const agentExamples = [
  '低估值高分红的银行股',
  '找最近强势突破的股票',
  '半导体行业里的大市值龙头',
  '白马股，ROE 高，估值不要太贵',
]

function getStructuredField(field) {
  return stockScreenTool.value?.fields?.find((item) => item.key === field)
}

function getStructuredOperatorOptions(condition) {
  return (getStructuredField(condition.field)?.operators || []).map((op) => ({
    label: operatorLabels[op] || op,
    value: op,
  }))
}

function updateStructuredField(condition, field) {
  const meta = getStructuredField(field)
  condition.field = field
  condition.op = meta?.data_type === 'text' && meta.operators.includes('in')
    ? 'in'
    : (meta?.operators?.[0] || 'eq')
  condition.value = meta?.data_type === 'text' ? '' : null
  condition.value2 = null
}

function addStructuredCondition() {
  structuredConditionId += 1
  structuredConditions.value.push({
    id: structuredConditionId,
    field: 'market_cap',
    op: 'gt',
    value: 100,
    value2: null,
  })
}

function removeStructuredCondition(id) {
  if (structuredConditions.value.length <= 1) return
  structuredConditions.value = structuredConditions.value.filter((item) => item.id !== id)
}

function formatStructuredCondition(condition) {
  const field = fieldLabelMap.value[condition.field] || condition.field
  const op = operatorLabels[condition.op] || condition.op
  if (condition.op === 'between') return `${field}${op}${condition.value ?? '—'} 至 ${condition.value2 ?? '—'}`
  return `${field}${op}${condition.value ?? '—'}`
}

function normalizeStructuredCondition(condition) {
  const meta = getStructuredField(condition.field)
  if (!meta) throw new Error(`不支持的筛选字段：${condition.field}`)

  if (meta.data_type === 'text') {
    const text = String(condition.value || '').trim()
    if (!text) throw new Error(`${meta.label}不能为空`)
    return {
      field: condition.field,
      op: condition.op,
      value: condition.op === 'in' ? text.split(/[,，、\s]+/).filter(Boolean) : text,
    }
  }

  if (condition.op === 'between') {
    const low = Number(condition.value)
    const high = Number(condition.value2)
    if (!Number.isFinite(low) || !Number.isFinite(high)) throw new Error(`${meta.label}区间必须填写两个数字`)
    if (low > high) throw new Error(`${meta.label}区间下限不能高于上限`)
    return { field: condition.field, op: condition.op, value: [low, high] }
  }

  const value = Number(condition.value)
  if (!Number.isFinite(value)) throw new Error(`${meta.label}必须填写数字`)
  return { field: condition.field, op: condition.op, value }
}

function mapScreenRows(items, labels) {
  return items.map((item) => {
    const metrics = {
      PE: item.pe,
      PB: item.pb,
      ROE: item.roe,
      市值: item.market_cap,
      股息率: item.dividend_yield,
      换手率: item.turnover,
    }
    const missingMetrics = Object.entries(metrics)
      .filter(([, value]) => value === null || value === undefined)
      .map(([label]) => label)
    return {
      ...item,
      score: null,
      signals: labels.length ? labels : ['条件筛选'],
      metrics,
      missingMetrics,
    }
  })
}

const columns = [
  {
    title: '股票',
    key: 'stock',
    width: 180,
    render(row) {
      return h('div', { class: 'stock-cell' }, [
        h('button', {
          class: 'stock-link',
          onClick: () => router.push(`/detail/${row.code}`),
        }, row.name || row.code),
        h('span', { class: 'stock-code' }, row.code),
      ])
    },
  },
  { title: '行业', key: 'industry', width: 130, render: (row) => row.industry || '-' },
  { title: '收盘价', key: 'close', width: 100, render: (row) => row.close?.toFixed?.(2) || '-' },
  {
    title: '涨跌幅',
    key: 'change_pct',
    width: 100,
    render(row) {
      const value = row.change_pct
      if (value == null) return '-'
      return h('span', { class: value >= 0 ? 'up' : 'down' }, `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`)
    },
  },
  { title: '策略得分', key: 'score', width: 100, sorter: 'default', render: (row) => row.score?.toFixed?.(1) || '-' },
  {
    title: '命中原因',
    key: 'signals',
    render(row) {
      return h(NSpace, { size: 6 }, {
        default: () => (row.signals || []).map((text) => h(NTag, { size: 'small', bordered: false }, { default: () => text })),
      })
    },
  },
  {
    title: '关键指标',
    key: 'metrics',
    minWidth: 220,
    render(row) {
      const metrics = Object.entries(row.metrics || {})
        .filter(([, value]) => value !== null && value !== undefined)
        .map(([key, value]) => `${key}: ${formatMetric(key, value)}`)
      return h('div', { class: 'metrics-line' }, metrics.join(' / ') || '-')
    },
  },
  {
    title: '数据状态',
    key: 'data_status',
    width: 100,
    render(row) {
      if (!row.missingMetrics) return '-'
      const missing = row.missingMetrics
      return h(NTag, {
        size: 'small',
        bordered: false,
        type: missing.length ? 'warning' : 'success',
        title: missing.length ? `缺失：${missing.join('、')}` : '关键字段完整',
      }, { default: () => missing.length ? `缺失 ${missing.length} 项` : '字段完整' })
    },
  },
]

function formatMetric(key, value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  if (key === '市值') return `${number.toFixed(0)}亿`
  if (key === '股息率' || key === 'ROE' || key === '换手率') return `${number.toFixed(2)}%`
  return number.toFixed(2)
}

async function runSelection(id = activeId.value) {
  if (!id) return
  loading.value = true
  errorMsg.value = ''
  agentResult.value = null
  structuredResult.value = null
  try {
    activeId.value = id
    result.value = await selectStrategy(id, { limit: 80 })
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || err.message || '策略选股失败'
  } finally {
    loading.value = false
  }
}

async function runAgent() {
  const query = agentQuery.value.trim()
  if (!query) return
  agentLoading.value = true
  agentError.value = ''
  errorMsg.value = ''
  structuredResult.value = null
  try {
    const data = await runStrategyAgent(query, { limit: 80 })
    agentResult.value = data
    if (data.plan?.strategy_id) activeId.value = data.plan.strategy_id
    if (data.strategy_result) result.value = data.strategy_result
  } catch (err) {
    agentError.value = err.response?.data?.detail || err.message || 'Agent 选股失败'
  } finally {
    agentLoading.value = false
  }
}

async function runStructuredScreen() {
  structuredLoading.value = true
  structuredError.value = ''
  errorMsg.value = ''
  try {
    const conditions = structuredConditions.value.map(normalizeStructuredCondition)
    const data = await screenStocks(conditions, {
      logic: structuredLogic.value,
      sort_by: structuredSortBy.value || undefined,
      sort_desc: structuredSortDesc.value,
      limit: 80,
    })
    structuredResult.value = data
    agentResult.value = null
    result.value = null
  } catch (err) {
    structuredError.value = err.response?.data?.detail || err.message || '结构化筛选失败'
  } finally {
    structuredLoading.value = false
  }
}

function useExample(text) {
  agentQuery.value = text
  runAgent()
}

async function bootstrap() {
  loading.value = true
  aiStatus.startAutoProbe()
  try {
    const [templateData, toolData] = await Promise.all([
      getStrategyTemplates(),
      getStrategyTools(),
    ])
    templates.value = templateData
    tools.value = toolData
    activeId.value = templates.value.find((item) => item.id === 'rps_breakout')?.id || templates.value[0]?.id || ''
    await runSelection(activeId.value)
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || err.message || '策略加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(bootstrap)
</script>

<template>
  <Shell>
    <div class="strategy-page">
      <section class="hero">
        <div>
          <div class="eyebrow">Agent 驱动 · 策略选股</div>
          <h1>策略选股</h1>
          <p>用自然语言描述目标，Agent 先规划筛选工具，再调用本地策略或结构化筛选引擎返回真实股票池。</p>
        </div>
        <n-button secondary strong @click="runSelection()" :loading="loading">刷新选股</n-button>
      </section>

      <n-card size="small" :bordered="true" class="agent-card">
        <div class="agent-shell">
          <div class="agent-copy">
            <strong>Agent 选股</strong>
            <span>自然语言目标 → 工具规划 → 本地筛选/策略执行 → 可解释结果</span>
            <span class="ai-health">
              AI 服务：{{ aiStatus.isUp ? '可用' : (aiStatus.reason || '不可用') }}
              <template v-if="aiStatus.latencyMs"> · {{ aiStatus.latencyMs }}ms</template>
            </span>
          </div>
          <div class="agent-input">
            <n-input
              v-model:value="agentQuery"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 3 }"
              placeholder="例如：低估值高分红的银行股 / 找最近强势突破的股票"
              @keydown.enter.exact.prevent="runAgent"
            />
            <n-button type="primary" strong :loading="agentLoading" @click="runAgent">运行 Agent</n-button>
          </div>
        </div>
        <div class="agent-examples">
          <n-button
            v-for="item in agentExamples"
            :key="item"
            size="tiny"
            secondary
            @click="useExample(item)"
          >
            {{ item }}
          </n-button>
        </div>
        <n-alert v-if="agentError" type="error" :bordered="false" class="notice compact">
          {{ agentError }}
        </n-alert>
        <div v-if="agentResult" class="agent-result">
          <div class="agent-meta">
            <n-tag size="small" :bordered="false">{{ agentResult.plan.tool_label }}</n-tag>
            <n-tag size="small" :bordered="false" :type="agentResult.plan.ai_used ? 'success' : 'warning'">
              {{ agentResult.plan.ai_used ? 'AI 已参与规划' : '本地规则规划' }}
            </n-tag>
            <span>命中 {{ displayTotal }} 只，当前展示 {{ rows.length }} 只</span>
          </div>

          <div class="agent-breakdown">
            <div class="agent-panel agent-panel-wide">
              <span class="panel-kicker">目标理解</span>
              <strong>{{ agentResult.query }}</strong>
              <p>{{ agentResult.plan.reasoning }}</p>
              <div class="agent-answer">{{ agentResult.answer }}</div>
            </div>

            <div class="agent-panel">
              <span class="panel-kicker">筛选条件</span>
              <div class="condition-list">
                <n-tag
                  v-for="condition in agentConditionList"
                  :key="condition"
                  size="small"
                  :bordered="false"
                >
                  {{ condition }}
                </n-tag>
              </div>
              <small>排序：{{ agentSortText }}</small>
            </div>

            <div class="agent-panel">
              <span class="panel-kicker">工具调用</span>
              <div class="tool-trace">
                <code v-for="trace in agentToolTrace" :key="trace">{{ trace }}</code>
              </div>
              <small>{{ activeTool?.description }}</small>
            </div>

            <div class="agent-panel">
              <span class="panel-kicker">前排命中</span>
              <div v-if="agentTopHits.length" class="hit-list">
                <button
                  v-for="hit in agentTopHits"
                  :key="hit.code"
                  type="button"
                  @click="router.push(`/detail/${hit.code}`)"
                >
                  <span>
                    <strong>{{ hit.name }}</strong>
                    <small>{{ hit.code }} · {{ hit.industry }}</small>
                  </span>
                  <em :class="(hit.change_pct || 0) >= 0 ? 'up' : 'down'">
                    {{ hit.change_pct == null ? '-' : `${hit.change_pct >= 0 ? '+' : ''}${hit.change_pct.toFixed(2)}%` }}
                  </em>
                </button>
              </div>
              <small v-else>当前没有命中股票。</small>
            </div>

            <div class="agent-panel agent-panel-wide">
              <span class="panel-kicker">风险与数据说明</span>
              <ul class="risk-list">
                <li v-for="note in agentRiskNotes" :key="note">{{ note }}</li>
              </ul>
            </div>
          </div>
        </div>
      </n-card>

      <n-card size="small" :bordered="true" class="structured-card">
        <template #header>
          <div class="structured-head">
            <div>
              <strong>手动条件筛选</strong>
              <span>直接调用本地筛选引擎，适合明确的估值、财务、行业和规模条件。</span>
            </div>
            <n-button size="tiny" secondary @click="addStructuredCondition">添加条件</n-button>
          </div>
        </template>

        <div class="structured-toolbar">
          <div class="structured-control">
            <span>条件关系</span>
            <n-radio-group v-model:value="structuredLogic" size="small">
              <n-radio-button value="AND">全部满足</n-radio-button>
              <n-radio-button value="OR">满足任一</n-radio-button>
            </n-radio-group>
          </div>
          <div class="structured-control sort-control">
            <span>排序</span>
            <n-select v-model:value="structuredSortBy" :options="structuredSortOptions" size="small" />
            <n-button size="small" secondary @click="structuredSortDesc = !structuredSortDesc">
              {{ structuredSortDesc ? '降序' : '升序' }}
            </n-button>
          </div>
        </div>

        <div class="condition-builder">
          <div v-for="(condition, index) in structuredConditions" :key="condition.id" class="condition-row">
            <span class="condition-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <n-select
              :value="condition.field"
              :options="structuredFieldOptions"
              size="small"
              @update:value="updateStructuredField(condition, $event)"
            />
            <n-select v-model:value="condition.op" :options="getStructuredOperatorOptions(condition)" size="small" />
            <n-input
              v-if="getStructuredField(condition.field)?.data_type === 'text'"
              v-model:value="condition.value"
              size="small"
              placeholder="输入行业或市场，多个值用逗号分隔"
            />
            <template v-else>
              <n-input-number v-model:value="condition.value" size="small" placeholder="数值" />
              <n-input-number
                v-if="condition.op === 'between'"
                v-model:value="condition.value2"
                size="small"
                placeholder="上限"
              />
            </template>
            <n-button
              size="small"
              text
              type="error"
              :disabled="structuredConditions.length <= 1"
              @click="removeStructuredCondition(condition.id)"
            >
              移除
            </n-button>
          </div>
        </div>

        <div class="structured-foot">
          <div>
            <span>当前条件</span>
            <n-tag v-for="label in structuredConditionLabels" :key="label" size="small" :bordered="false">
              {{ label }}
            </n-tag>
          </div>
          <n-button type="primary" size="small" strong :loading="structuredLoading" @click="runStructuredScreen">
            执行筛选
          </n-button>
        </div>
        <n-alert v-if="structuredError" type="error" :bordered="false" class="notice compact">
          {{ structuredError }}
        </n-alert>
      </n-card>

      <div class="tool-workbench">
        <n-card
          v-for="tool in tools"
          :key="tool.id"
          size="small"
          :bordered="true"
          class="tool-card"
          :class="{ active: activeTool?.id === tool.id }"
        >
          <template #header>
            <div class="tool-head">
              <strong>{{ tool.label }}</strong>
              <n-tag size="tiny" :bordered="false">{{ tool.category }}</n-tag>
            </div>
          </template>
          <p>{{ tool.description }}</p>
          <div class="tool-io">
            <span>输入：{{ tool.inputs.join(' / ') }}</span>
            <span>输出：{{ tool.outputs.join(' / ') }}</span>
          </div>
          <div class="tool-examples">
            <n-tag
              v-for="example in tool.examples.slice(0, 3)"
              :key="example"
              size="small"
              :bordered="false"
            >
              {{ example }}
            </n-tag>
          </div>
        </n-card>
      </div>

      <n-card v-if="visibleFields.length" size="small" :bordered="true" class="field-card">
        <template #header>
          <div class="field-head">
            <strong>结构化筛选字段</strong>
            <span>Agent 只能基于这些本地字段生成筛选条件，缺失字段不会补假数据。</span>
          </div>
        </template>
        <div class="field-grid">
          <div v-for="field in visibleFields" :key="field.key" class="field-item">
            <div>
              <strong>{{ field.label }}</strong>
              <code>{{ field.key }}</code>
            </div>
            <span>{{ field.description }}</span>
          </div>
        </div>
      </n-card>

      <n-alert v-if="errorMsg" type="error" :bordered="false" class="notice">
        {{ errorMsg }}
      </n-alert>

      <n-grid :cols="4" :x-gap="12" :y-gap="12" responsive="screen" class="summary-grid">
        <n-grid-item v-for="item in summary" :key="item.label">
          <n-card size="small" :bordered="true" class="summary-card">
            <div class="summary-label">{{ item.label }}</div>
            <div class="summary-value">
              <n-number-animation v-if="item.value != null" :from="0" :to="item.value" />
              <span v-else>—</span>
              <span v-if="item.value != null">{{ item.suffix }}</span>
            </div>
          </n-card>
        </n-grid-item>
      </n-grid>

      <div class="main-grid">
        <aside class="strategy-list">
          <n-card title="策略库" size="small" :bordered="true">
            <div v-if="!templates.length && loading" class="loading-list">
              <n-skeleton v-for="i in 4" :key="i" text :repeat="2" />
            </div>
            <button
              v-for="tpl in templates"
              :key="tpl.id"
              class="strategy-item"
              :data-active="tpl.id === activeId"
              @click="runSelection(tpl.id)"
            >
              <span>
                <strong>{{ tpl.name }}</strong>
                <small>{{ tpl.description }}</small>
              </span>
              <n-tag size="small" :bordered="false">{{ tpl.tag }}</n-tag>
            </button>
          </n-card>

          <n-card v-if="activeTemplate" title="选股规则" size="small" :bordered="true">
            <ul class="rules">
              <li v-for="rule in activeTemplate.rules" :key="rule">{{ rule }}</li>
            </ul>
          </n-card>
        </aside>

        <section class="result-panel">
          <n-card size="small" :bordered="true">
            <template #header>
              <div class="table-head">
                <div>
                  <strong>{{ displayTitle }}</strong>
                  <span>交易日：{{ displayTradeDate }}</span>
                </div>
                <n-tag :bordered="false" type="success">
                  {{ agentResult ? 'Agent 工具结果' : (structuredResult ? '结构化筛选结果' : (activeTemplate?.source || '本地策略')) }}
                </n-tag>
              </div>
            </template>

            <n-data-table
              v-if="rows.length"
              :columns="columns"
              :data="rows"
              :loading="tableLoading"
              :pagination="{ pageSize: 20 }"
              size="small"
              striped
            />
            <n-empty v-else-if="!tableLoading" description="当前条件没有命中股票" />
            <div v-else class="table-loading">
              <n-skeleton text :repeat="8" />
            </div>
          </n-card>

          <n-alert v-if="result?.notes?.length" type="info" :bordered="false" class="notice">
            <div v-for="note in result.notes" :key="note">{{ note }}</div>
          </n-alert>
        </section>
      </div>
    </div>
  </Shell>
</template>

<style scoped>
.strategy-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 10px 0 4px;
}

.eyebrow {
  font-size: 12px;
  font-weight: 700;
  color: #16A34A;
  margin-bottom: 6px;
}

h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.15;
  color: #111111;
}

p {
  margin: 8px 0 0;
  color: #71717A;
  max-width: 680px;
}

.summary-grid {
  margin-top: 2px;
}

.agent-card {
  border-radius: 8px;
}

.agent-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 14px;
  align-items: stretch;
}

.agent-copy {
  padding: 4px 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.agent-copy strong {
  color: #111111;
  font-size: 16px;
}

.agent-copy span,
.agent-meta,
.tool-trace {
  color: #71717A;
  font-size: 12px;
  line-height: 1.55;
}

.ai-health {
  display: inline-flex;
  width: fit-content;
  padding: 3px 7px;
  border: 1px solid #E5E7EB;
  border-radius: 4px;
  background: #FFFFFF;
  color: #52525B;
  font-size: 11px;
}

.agent-input {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 108px;
  gap: 10px;
  align-items: stretch;
}

.agent-input :deep(.n-input) {
  border-radius: 6px;
}

.agent-input :deep(.n-button) {
  border-radius: 6px;
}

.agent-examples {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.agent-examples :deep(.n-button) {
  border-radius: 5px;
}

.agent-result {
  margin-top: 12px;
  padding: 10px;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FAFAFA;
}

.structured-card {
  border-radius: 6px;
}

.structured-card :deep(.n-card-header) {
  padding-bottom: 8px;
}

.structured-head,
.structured-toolbar,
.structured-foot,
.structured-control,
.condition-row {
  display: flex;
  align-items: center;
}

.structured-head,
.structured-foot {
  justify-content: space-between;
  gap: 12px;
}

.structured-head strong {
  display: block;
  color: #111111;
  font-size: 14px;
}

.structured-head span,
.structured-control > span,
.structured-foot > div > span {
  color: #71717A;
  font-size: 11px;
}

.structured-head span {
  display: block;
  margin-top: 3px;
}

.structured-toolbar {
  gap: 14px;
  padding: 7px 8px;
  border: 1px solid #EDEDED;
  border-radius: 5px;
  background: #FAFAFA;
}

.structured-control {
  gap: 7px;
}

.sort-control {
  margin-left: auto;
}

.sort-control :deep(.n-select) {
  width: 138px;
}

.condition-builder {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.condition-row {
  display: grid;
  grid-template-columns: 28px 142px 112px minmax(160px, 1fr) auto auto;
  gap: 7px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid #EDEDED;
  border-radius: 5px;
  background: #FFFFFF;
}

.condition-index {
  color: #A1A1AA;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
}

.structured-foot {
  margin-top: 8px;
}

.structured-foot > div {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.agent-breakdown {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr 0.85fr;
  gap: 8px;
  margin-top: 10px;
}

.agent-panel {
  min-height: 112px;
  padding: 10px;
  border: 1px solid #E5E7EB;
  border-radius: 5px;
  background: #FFFFFF;
}

.agent-panel-wide {
  grid-column: span 2;
}

.panel-kicker {
  display: block;
  margin-bottom: 7px;
  color: #71717A;
  font-size: 11px;
  font-weight: 700;
}

.agent-panel strong {
  color: #111111;
  font-size: 14px;
}

.agent-panel p,
.agent-panel small {
  display: block;
  max-width: none;
  margin: 6px 0 0;
  color: #71717A;
  font-size: 12px;
  line-height: 1.55;
}

.condition-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.hit-list {
  display: grid;
  gap: 5px;
}

.hit-list button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  border: 0;
  border-bottom: 1px solid #F4F4F5;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.hit-list button:last-child {
  border-bottom: 0;
}

.hit-list strong {
  display: block;
  font-size: 12px;
}

.hit-list small {
  margin: 1px 0 0;
  font-size: 11px;
}

.hit-list em {
  font-size: 12px;
  font-style: normal;
  font-weight: 700;
  white-space: nowrap;
}

.risk-list {
  margin: 0;
  padding-left: 16px;
  color: #52525B;
  font-size: 12px;
  line-height: 1.65;
}

.tool-workbench {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.tool-card {
  border-radius: 6px;
}

.tool-card.active {
  border-color: #111111;
  background: #FAFAFA;
}

.tool-card :deep(.n-card-header) {
  padding-bottom: 6px;
}

.tool-card :deep(.n-card__content) {
  padding-top: 0;
}

.tool-head,
.field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.tool-head strong,
.field-head strong {
  color: #111111;
  font-size: 14px;
}

.field-head span {
  color: #71717A;
  font-size: 12px;
  font-weight: 500;
}

.tool-card p {
  margin: 0 0 8px;
  max-width: none;
  color: #52525B;
  font-size: 12px;
  line-height: 1.55;
}

.tool-io {
  display: grid;
  gap: 4px;
  padding: 7px 8px;
  border: 1px solid #EDEDED;
  border-radius: 5px;
  background: #FFFFFF;
  color: #71717A;
  font-size: 11px;
  line-height: 1.45;
}

.tool-examples {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.field-card {
  border-radius: 6px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.field-item {
  min-height: 74px;
  padding: 9px 10px;
  border: 1px solid #EDEDED;
  border-radius: 5px;
  background: #FFFFFF;
}

.field-item > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 5px;
}

.field-item strong {
  color: #111111;
  font-size: 12px;
}

.field-item code {
  color: #71717A;
  font-size: 10px;
  font-family: 'IBM Plex Mono', monospace;
}

.field-item span {
  display: block;
  color: #71717A;
  font-size: 11px;
  line-height: 1.5;
}

.agent-answer {
  font-size: 13px;
  color: #111111;
  line-height: 1.65;
  font-weight: 650;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #F4F4F5;
}

.agent-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.tool-trace {
  display: grid;
  gap: 8px;
}

.tool-trace code {
  display: block;
  padding: 5px 6px;
  border-radius: 4px;
  background: #FAFAFA;
  border: 1px solid #E5E7EB;
  color: #3F3F46;
  font-size: 11px;
  white-space: normal;
  word-break: break-all;
}

.summary-card {
  border-radius: 8px;
}

.summary-label {
  color: #71717A;
  font-size: 12px;
  margin-bottom: 8px;
}

.summary-value {
  font-size: 24px;
  font-weight: 800;
  color: #111111;
  display: flex;
  gap: 2px;
  align-items: baseline;
}

.summary-value span {
  font-size: 13px;
  color: #71717A;
}

.main-grid {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

.strategy-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.strategy-item {
  width: 100%;
  border: 1px solid #EDEDED;
  background: #FFFFFF;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  text-align: left;
  cursor: pointer;
  margin-bottom: 8px;
}

.strategy-item[data-active="true"] {
  border-color: #111111;
  background: #FAFAFA;
}

.strategy-item strong {
  display: block;
  color: #111111;
  margin-bottom: 4px;
}

.strategy-item small {
  display: block;
  color: #71717A;
  line-height: 1.45;
}

.rules {
  margin: 0;
  padding-left: 18px;
  color: #3F3F46;
  line-height: 1.75;
}

.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.table-head span {
  margin-left: 10px;
  color: #71717A;
  font-size: 12px;
}

.stock-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stock-link {
  border: 0;
  background: transparent;
  padding: 0;
  color: #111111;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

.stock-code,
.metrics-line {
  color: #71717A;
  font-size: 12px;
}

.up {
  color: #16A34A;
  font-weight: 700;
}

.down {
  color: #DC2626;
  font-weight: 700;
}

.notice {
  border-radius: 8px;
}

.notice.compact {
  margin-top: 10px;
  font-size: 12px;
}

.table-loading,
.loading-list {
  padding: 12px;
}

@media (max-width: 960px) {
  .hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .main-grid {
    grid-template-columns: 1fr;
  }

  .tool-workbench,
  .field-grid,
  .agent-breakdown {
    grid-template-columns: 1fr;
  }

  .structured-toolbar,
  .structured-foot {
    align-items: flex-start;
    flex-direction: column;
  }

  .sort-control {
    width: 100%;
    margin-left: 0;
  }

  .sort-control :deep(.n-select) {
    flex: 1;
    width: auto;
  }

  .condition-row {
    grid-template-columns: 24px minmax(0, 1fr) minmax(0, 0.9fr);
  }

  .condition-row :deep(.n-input),
  .condition-row :deep(.n-input-number) {
    grid-column: 2 / span 2;
    width: 100%;
  }

  .agent-panel-wide {
    grid-column: auto;
  }

  .agent-shell,
  .agent-input {
    grid-template-columns: 1fr;
  }
}
</style>
