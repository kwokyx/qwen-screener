<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NInput,
  NInputNumber,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NTag,
} from 'naive-ui'
import Shell from '../components/Shell.vue'
import { screen as screenStocks } from '../api/screener'
import { getStrategyTemplates, getStrategyTools, selectStrategy } from '../api/strategy'

const router = useRouter()

const templates = ref([])
const tools = ref([])
const activeId = ref('')
const result = ref(null)
const structuredResult = ref(null)
const loading = ref(false)
const bootstrapLoading = ref(true)
const structuredLoading = ref(false)
const errorMsg = ref('')
const structuredError = ref('')
let structuredConditionId = 2
const structuredConditions = ref([
  { id: 1, field: 'pe', op: 'lt', value: 20, value2: null },
  { id: 2, field: 'roe', op: 'gt', value: 10, value2: null },
])
const structuredLogic = ref('AND')
const structuredSortBy = ref('market_cap')
const structuredSortDesc = ref(true)
const workspaceMode = ref('structured')
const storageReady = ref(false)
const STATE_STORAGE_KEY = 'qwen-stock:strategy-page-state:v1'

const activeTemplate = computed(() => templates.value.find((item) => item.id === activeId.value))
const rows = computed(() => {
  const screen = structuredResult.value
  if (screen) {
    return mapScreenRows(screen.items || [], structuredConditionLabels.value)
  }
  return result.value?.items || []
})
const displayTotal = computed(() => structuredResult.value?.total ?? result.value?.total ?? 0)
const displayTradeDate = computed(() => structuredResult.value?.items?.[0]?.trade_date
  || structuredResult.value?.items?.[0]?.trade_date
  || result.value?.trade_date
  || '-')
const displayTitle = computed(() => {
  if (loading.value && workspaceMode.value === 'strategy') {
    return activeTemplate.value ? `正在计算：${activeTemplate.value.name}` : '正在计算策略'
  }
  if (!hasResult.value) {
    if (workspaceMode.value === 'strategy' && activeTemplate.value) return `待筛选：${activeTemplate.value.name}`
    return '待筛选'
  }
  if (structuredResult.value) return '结构化条件筛选'
  return activeTemplate.value?.name || '策略'
})
const stockScreenTool = computed(() => tools.value.find((item) => item.id === 'stock_screen'))
const strategyTool = computed(() => tools.value.find((item) => item.id === 'strategy_select'))
const activeTool = computed(() => {
  if (structuredResult.value) return stockScreenTool.value
  return strategyTool.value || tools.value[0]
})
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
const isBusy = computed(() => loading.value || structuredLoading.value)
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
const tableLoading = computed(() => loading.value || structuredLoading.value)
const hasResult = computed(() => Boolean(structuredResult.value || result.value))
const resultSourceLabel = computed(() => {
  if (loading.value && workspaceMode.value === 'strategy') return '计算中'
  if (structuredResult.value) return '条件筛选'
  if (result.value) return '内置策略'
  return '待筛选'
})
const resultSourceType = computed(() => {
  if (loading.value && workspaceMode.value === 'strategy') return 'info'
  if (!hasResult.value) return 'default'
  return 'success'
})
const tableLoadingText = computed(() => {
  if (loading.value && workspaceMode.value === 'strategy') return '正在计算策略'
  if (structuredLoading.value) return '正在执行条件筛选'
  return '正在加载选股结果'
})

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
          onClick: () => gotoDetail(row.code),
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
      }, { default: () => missing.length === 1 ? `缺${missing[0]}` : missing.length ? `缺失 ${missing.length} 项` : '字段完整' })
    },
  },
]

function gotoDetail(code) {
  persistState()
  router.push(`/detail/${code}`)
}
const displayColumns = computed(() => {
  return columns
})

function formatMetric(key, value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  if (key === '市值') return `${number.toFixed(0)}亿`
  if (key === '股息率' || key === 'ROE' || key === '换手率') return `${number.toFixed(2)}%`
  return number.toFixed(2)
}

async function runSelection(id = activeId.value) {
  if (!id || isBusy.value) return
  loading.value = true
  errorMsg.value = ''
  structuredResult.value = null
  result.value = null
  try {
    activeId.value = id
    result.value = await selectStrategy(id, { limit: 80 })
    persistState()
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || err.message || '策略选股失败'
  } finally {
    loading.value = false
  }
}

async function runStructuredScreen() {
  if (isBusy.value) return
  structuredLoading.value = true
  structuredError.value = ''
  errorMsg.value = ''
  structuredResult.value = null
  result.value = null
  try {
    const conditions = structuredConditions.value.map(normalizeStructuredCondition)
    const data = await screenStocks(conditions, {
      logic: structuredLogic.value,
      sort_by: structuredSortBy.value || undefined,
      sort_desc: structuredSortDesc.value,
      limit: 80,
    })
    structuredResult.value = data
    result.value = null
    persistState()
  } catch (err) {
    structuredError.value = err.response?.data?.detail || err.message || '结构化筛选失败'
  } finally {
    structuredLoading.value = false
  }
}

function chooseStrategy(id) {
  if (isBusy.value) return
  workspaceMode.value = 'strategy'
  activeId.value = id
  structuredResult.value = null
  result.value = null
  errorMsg.value = ''
}

function readSavedState() {
  try {
    const raw = window.sessionStorage.getItem(STATE_STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch (err) {
    return null
  }
}

function restoreSavedState() {
  const saved = readSavedState()
  if (!saved || saved.version !== 1) return

  if (['structured', 'strategy'].includes(saved.workspaceMode)) {
    workspaceMode.value = saved.workspaceMode
  }
  if (saved.activeId && templates.value.some((item) => item.id === saved.activeId)) {
    activeId.value = saved.activeId
  }
  if (Array.isArray(saved.structuredConditions) && saved.structuredConditions.length) {
    structuredConditions.value = saved.structuredConditions
    structuredConditionId = Math.max(...saved.structuredConditions.map((item) => Number(item.id) || 0), structuredConditionId)
  }
  if (['AND', 'OR'].includes(saved.structuredLogic)) {
    structuredLogic.value = saved.structuredLogic
  }
  if (typeof saved.structuredSortBy === 'string') {
    structuredSortBy.value = saved.structuredSortBy
  }
  if (typeof saved.structuredSortDesc === 'boolean') {
    structuredSortDesc.value = saved.structuredSortDesc
  }

  result.value = saved.result || null
  structuredResult.value = saved.structuredResult || null
}

function persistState() {
  if (!storageReady.value) return
  try {
    window.sessionStorage.setItem(STATE_STORAGE_KEY, JSON.stringify({
      version: 1,
      workspaceMode: workspaceMode.value,
      activeId: activeId.value,
      structuredConditions: structuredConditions.value,
      structuredLogic: structuredLogic.value,
      structuredSortBy: structuredSortBy.value,
      structuredSortDesc: structuredSortDesc.value,
      result: result.value,
      structuredResult: structuredResult.value,
    }))
  } catch (err) {
    // Session storage can be unavailable in private or embedded browser contexts.
  }
}

async function bootstrap() {
  bootstrapLoading.value = true
  let didLoad = false
  try {
    const [templateData, toolData] = await Promise.all([
      getStrategyTemplates(),
      getStrategyTools(),
    ])
    templates.value = templateData
    tools.value = toolData
    activeId.value = templates.value.find((item) => item.id === 'rps_breakout')?.id || templates.value[0]?.id || ''
    restoreSavedState()
    didLoad = true
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || err.message || '策略加载失败'
  } finally {
    if (didLoad) {
      storageReady.value = true
      persistState()
    }
    bootstrapLoading.value = false
  }
}

onMounted(bootstrap)

watch([
  workspaceMode,
  activeId,
  structuredConditions,
  structuredLogic,
  structuredSortBy,
  structuredSortDesc,
  result,
  structuredResult,
], persistState, { deep: true })
</script>

<template>
  <Shell>
    <div class="strategy-page">
      <section class="page-head">
        <div>
          <h1>策略选股</h1>
          <span>交易日 {{ displayTradeDate }}</span>
        </div>
        <n-button
          size="small"
          type="primary"
          secondary
          :disabled="workspaceMode !== 'strategy' || !activeId || isBusy"
          :loading="loading"
          @click="runSelection()"
        >
          执行策略筛选
        </n-button>
      </section>

      <n-card size="small" :bordered="true" class="workspace-card">
        <div class="workspace-bar">
          <n-radio-group v-model:value="workspaceMode" size="small" :disabled="isBusy">
            <n-radio-button value="structured">条件选股</n-radio-button>
            <n-radio-button value="strategy">策略选股</n-radio-button>
          </n-radio-group>
        </div>

        <div v-if="workspaceMode === 'structured'" class="mode-panel">
          <div class="structured-toolbar">
            <div class="structured-control">
              <span>关系</span>
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
            <n-button size="small" secondary :disabled="isBusy" @click="addStructuredCondition">添加条件</n-button>
          </div>

          <div class="condition-builder">
            <div v-for="(condition, index) in structuredConditions" :key="condition.id" class="condition-row">
              <span class="condition-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <n-select
                :value="condition.field"
                :options="structuredFieldOptions"
                size="small"
                :disabled="isBusy"
                @update:value="updateStructuredField(condition, $event)"
              />
              <n-select v-model:value="condition.op" :options="getStructuredOperatorOptions(condition)" size="small" :disabled="isBusy" />
              <n-input
                v-if="getStructuredField(condition.field)?.data_type === 'text'"
                v-model:value="condition.value"
                size="small"
                :disabled="isBusy"
                placeholder="输入值"
              />
              <template v-else>
                <n-input-number v-model:value="condition.value" size="small" :disabled="isBusy" placeholder="数值" />
                <n-input-number
                  v-if="condition.op === 'between'"
                  v-model:value="condition.value2"
                  size="small"
                  :disabled="isBusy"
                  placeholder="上限"
                />
              </template>
              <n-button
                size="small"
                text
                type="error"
                :disabled="structuredConditions.length <= 1 || isBusy"
                @click="removeStructuredCondition(condition.id)"
              >
                删除
              </n-button>
            </div>
          </div>

          <div class="structured-foot">
            <div>
              <n-tag v-for="label in structuredConditionLabels" :key="label" size="small" :bordered="false">
                {{ label }}
              </n-tag>
            </div>
            <n-button type="primary" size="small" strong :disabled="isBusy" :loading="structuredLoading" @click="runStructuredScreen">
              执行筛选
            </n-button>
          </div>
          <n-alert v-if="structuredError" type="error" :bordered="false" class="notice compact">
            {{ structuredError }}
          </n-alert>
        </div>

        <div v-else-if="bootstrapLoading" class="strategy-picker">
          <div v-for="n in 4" :key="'strategy-sk-' + n" class="strategy-item skeleton-card" aria-hidden="true">
            <span>
              <span class="sk-line title"></span>
              <span class="sk-line desc"></span>
            </span>
            <span class="sk-pill"></span>
          </div>
        </div>
        <div v-else class="strategy-picker">
          <button
            v-for="tpl in templates"
            :key="tpl.id"
            class="strategy-item"
            :data-active="tpl.id === activeId"
            :disabled="isBusy"
            @click="chooseStrategy(tpl.id)"
          >
            <span>
              <strong>{{ tpl.name }}</strong>
              <small>{{ tpl.description }}</small>
            </span>
            <n-tag size="small" :bordered="false">{{ tpl.tag }}</n-tag>
          </button>
          <div class="strategy-action">
            <span>选择策略后不会自动筛选，确认规则后再执行。</span>
            <n-button type="primary" size="small" strong :disabled="!activeId || isBusy" :loading="loading" @click="runSelection()">
              执行策略筛选
            </n-button>
          </div>
        </div>
      </n-card>

      <n-alert v-if="errorMsg" type="error" :bordered="false" class="notice">
        {{ errorMsg }}
      </n-alert>

      <section class="result-panel">
        <n-card size="small" :bordered="true">
          <template #header>
            <div class="table-head">
              <div>
                <strong>{{ displayTitle }}</strong>
                <span v-if="hasResult">{{ displayTotal }} 只命中</span>
                <span v-else-if="tableLoading">请稍候，正在计算</span>
                <span v-else>点击筛选后显示结果</span>
              </div>
              <n-tag :bordered="false" size="small" :type="resultSourceType">
                {{ resultSourceLabel }}
              </n-tag>
            </div>
          </template>

          <n-data-table
            v-if="rows.length"
            :columns="displayColumns"
            :data="rows"
            :loading="tableLoading"
            :pagination="{ pageSize: 20 }"
            size="small"
            striped
          />
          <n-empty
            v-else-if="!tableLoading"
            :description="hasResult ? '当前条件没有命中股票' : '请选择策略或输入条件，点击筛选后显示结果'"
          />
          <div v-else class="table-loading">
            <div class="loading-title">{{ tableLoadingText }}</div>
            <div v-for="n in 6" :key="n" class="strategy-skeleton-row">
              <span class="sk-cell name"></span>
              <span class="sk-cell industry"></span>
              <span class="sk-cell num"></span>
              <span class="sk-cell num"></span>
              <span class="sk-cell reason"></span>
            </div>
          </div>
        </n-card>

        <details v-if="workspaceMode === 'strategy' && activeTemplate" class="details-panel">
          <summary>查看策略规则</summary>
          <ul class="rules">
            <li v-for="rule in activeTemplate.rules" :key="rule">{{ rule }}</li>
          </ul>
        </details>

        <details v-if="result?.notes?.length" class="details-panel">
          <summary>查看数据说明</summary>
          <div v-for="note in result.notes" :key="note" class="detail-note">{{ note }}</div>
        </details>
      </section>
    </div>
  </Shell>
</template>

<style scoped>
.strategy-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.page-head,
.workspace-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.page-head {
  padding: 2px 0;
}

.page-head span {
  display: block;
  margin-top: 3px;
  color: #71717A;
  font-size: 12px;
}

.workspace-card,
.result-panel :deep(.n-card) {
  border-radius: 5px;
}

.workspace-bar {
  padding-bottom: 10px;
  border-bottom: 1px solid #EDEDED;
}

.mode-panel {
  padding-top: 10px;
}

.strategy-picker {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  padding-top: 10px;
}

.details-panel {
  margin-top: 8px;
  border: 1px solid #E5E7EB;
  border-radius: 5px;
  background: #FFFFFF;
  color: #52525B;
  font-size: 12px;
}

.details-panel summary {
  padding: 8px 10px;
  color: #3F3F46;
  cursor: pointer;
  font-weight: 700;
}

.detail-note {
  padding: 0 10px 8px;
  line-height: 1.6;
}

h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.15;
  color: #111111;
}

.structured-toolbar,
.structured-foot,
.structured-control,
.condition-row {
  display: flex;
  align-items: center;
}

.structured-foot {
  justify-content: space-between;
  gap: 12px;
}

.structured-control > span {
  color: #71717A;
  font-size: 11px;
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

.strategy-item {
  width: 100%;
  border: 1px solid #EDEDED;
  background: #FFFFFF;
  border-radius: 5px;
  padding: 9px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  text-align: left;
  cursor: pointer;
  margin-bottom: 0;
}

.strategy-item[data-active="true"] {
  border-color: #111111;
  background: #FAFAFA;
}

.strategy-item:disabled {
  cursor: wait;
  opacity: 0.68;
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

.strategy-action {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 10px;
  border: 1px solid #EDEDED;
  border-radius: 5px;
  background: #FAFAFA;
  color: #71717A;
  font-size: 12px;
}

.skeleton-card {
  cursor: default;
}

.sk-line,
.sk-pill,
.sk-cell {
  display: block;
  overflow: hidden;
  border-radius: 999px;
  background: linear-gradient(90deg, #EFEFEF 0%, #DDDDDD 46%, #F5F5F5 62%, #EFEFEF 100%);
  background-size: 220% 100%;
  animation: sk-shimmer 1.35s ease-in-out infinite;
}

.sk-line.title {
  width: 112px;
  height: 13px;
  margin-bottom: 8px;
}

.sk-line.desc {
  width: min(260px, 86%);
  height: 10px;
}

.sk-pill {
  width: 52px;
  height: 22px;
  border-radius: 5px;
  flex: 0 0 auto;
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

.stock-link:hover {
  color: #0F766E;
}

.stock-link:focus-visible {
  outline: 2px solid #99F6E4;
  outline-offset: 2px;
  border-radius: 3px;
}

.stock-code,
.metrics-line {
  color: #71717A;
  font-size: 12px;
}

.up {
  color: #DC2626;
  font-weight: 700;
}

.down {
  color: #16A34A;
  font-weight: 700;
}

.notice {
  border-radius: 5px;
}

.notice.compact {
  margin-top: 10px;
  font-size: 12px;
}

.table-loading,
.loading-list {
  padding: 10px 12px 14px;
}

.loading-title {
  margin-bottom: 8px;
  color: #71717A;
  font-size: 12px;
}

.strategy-skeleton-row {
  display: grid;
  grid-template-columns: minmax(140px, 1.2fr) 120px 90px 90px minmax(220px, 2fr);
  gap: 12px;
  align-items: center;
  min-height: 34px;
  border-top: 1px solid #F1F1F1;
}

.strategy-skeleton-row:first-of-type {
  border-top: 0;
}

.sk-cell {
  height: 10px;
}

.sk-cell.name { width: 70%; }
.sk-cell.industry { width: 62%; }
.sk-cell.num { width: 58px; justify-self: end; }
.sk-cell.reason { width: 86%; }

@keyframes sk-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -80% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .sk-cell {
    animation: none;
  }

  .sk-line,
  .sk-pill {
    animation: none;
  }
}

@media (max-width: 960px) {
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

}

@media (max-width: 640px) {
  .strategy-picker {
    grid-template-columns: 1fr;
  }

  .workspace-bar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
