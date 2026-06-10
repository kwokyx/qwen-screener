<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
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
import StarButton from '../components/StarButton.vue'
import { screen as screenStocks } from '../api/screener'
import { getStrategyTemplates, getStrategyTools, selectStrategy } from '../api/strategy'
import { industries as fetchIndustries } from '../api/market'
import { useAuthStore } from '../stores/auth'
import { toast } from '../stores/toast'
import { useWatchlistStore } from '../stores/watchlist'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const wl = useWatchlistStore()

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
let structuredConditionId = 0
const structuredConditions = ref([])
const structuredLogic = ref('AND')
const structuredSortBy = ref('market_cap')
const structuredSortDesc = ref(true)
const workspaceMode = ref('structured')
const storageReady = ref(false)
const selectedRowKeys = ref([])
const industryOptions = ref([])
const industryLoading = ref(false)
const STATE_STORAGE_KEY = 'qwen-stock:strategy-page-state:v1'
const SAVED_FILTERS_KEY = 'qwen-stock:saved-condition-strategies:v1'
const savedConditionStrategies = ref([])
const activeSavedConditionId = ref('')
const saveConditionName = ref('')
const saveConditionError = ref('')

const activeTemplate = computed(() => templates.value.find((item) => item.id === activeId.value))
const rows = computed(() => {
  const screen = structuredResult.value
  if (screen) {
    return mapScreenRows(screen.items || [], structuredConditionLabels.value)
  }
  return result.value?.items || []
})
const selectedKeySet = computed(() => new Set(selectedRowKeys.value))
const selectedRows = computed(() => rows.value.filter((item) => item?.code && selectedKeySet.value.has(item.code)))
const selectedWatchCandidates = computed(() => selectedRows.value.filter((item) => item?.code && !wl.has(item.code)))
const batchWatchLabel = computed(() => {
  if (!selectedRows.value.length) return '选择后加入自选'
  if (!selectedWatchCandidates.value.length) return '已选已加入'
  return `加入已选 ${selectedWatchCandidates.value.length}`
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
const conditionFieldGroups = [
  {
    key: 'fundamental',
    label: '基本面',
    fields: ['pe', 'pb', 'roe', 'market_cap', 'dividend_yield', 'revenue_yoy', 'profit_yoy', 'gross_margin', 'debt_ratio'],
  },
  {
    key: 'technical',
    label: '技术面',
    fields: ['close', 'turnover', 'ma5', 'ma20', 'volume_ratio_20', 'breakout_20', 'ma5_above_ma20', 'pct_change_20'],
  },
  {
    key: 'scope',
    label: '选股范围',
    fields: ['industry', 'market', 'risk_flag'],
  },
]
const structuredFieldOptions = computed(() => {
  const fields = stockScreenTool.value?.fields || []
  const fieldMap = new Map(fields.map((field) => [field.key, field]))
  const groupedKeys = new Set(conditionFieldGroups.flatMap((group) => group.fields))
  const groups = conditionFieldGroups
    .map((group) => ({
      type: 'group',
      key: group.key,
      label: group.label,
      children: group.fields
        .map((key) => fieldMap.get(key))
        .filter(Boolean)
        .map((field) => ({ label: field.label, value: field.key })),
    }))
    .filter((group) => group.children.length)
  const otherFields = fields
    .filter((field) => !groupedKeys.has(field.key))
    .map((field) => ({ label: field.label, value: field.key }))
  if (otherFields.length) {
    groups.push({
      type: 'group',
      key: 'other',
      label: '其他',
      children: otherFields,
    })
  }
  return groups
})
const structuredSortOptions = computed(() => [
  { label: '默认排序', value: '' },
  ...(stockScreenTool.value?.fields || [])
    .filter((field) => field.data_type === 'number')
    .map((field) => ({ label: field.label, value: field.key })),
])
const industrySelectOptions = computed(() => industryOptions.value.map((item) => ({
  label: `${item.name}（${item.count}）`,
  value: item.name,
})))
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

function isIndustryCondition(condition) {
  return condition.field === 'industry'
}

function updateStructuredField(condition, field) {
  const meta = getStructuredField(field)
  condition.field = field
  condition.op = meta?.data_type === 'text' && meta.operators.includes('in')
    ? 'in'
    : (meta?.operators?.[0] || 'eq')
  condition.value = field === 'industry' && condition.op === 'in'
    ? []
    : (meta?.data_type === 'text' ? '' : null)
  condition.value2 = null
}

function updateStructuredOperator(condition, op) {
  condition.op = op
  condition.value2 = null
  if (!isIndustryCondition(condition)) return
  const values = normalizeIndustryValues(condition.value)
  condition.value = op === 'in' ? values : (values[0] || null)
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
  structuredConditions.value = structuredConditions.value.filter((item) => item.id !== id)
}

function formatStructuredCondition(condition) {
  const field = fieldLabelMap.value[condition.field] || condition.field
  const op = operatorLabels[condition.op] || condition.op
  if (condition.op === 'between') return `${field}${op}${condition.value ?? '—'} 至 ${condition.value2 ?? '—'}`
  return `${field}${op}${formatConditionValue(condition.value)}`
}

function normalizeStructuredCondition(condition) {
  const meta = getStructuredField(condition.field)
  if (!meta) throw new Error(`不支持的筛选字段：${condition.field}`)

  if (condition.field === 'industry') {
    const values = normalizeIndustryValues(condition.value)
    if (!values.length) throw new Error('行业不能为空')
    return {
      field: condition.field,
      op: condition.op,
      value: condition.op === 'in' ? values : values[0],
    }
  }

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

function normalizeIndustryValues(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean)
  const text = String(value || '').trim()
  return text ? text.split(/[,，、\s]+/).filter(Boolean) : []
}

function formatConditionValue(value) {
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  return value ?? '—'
}

function cloneConditionValue(value) {
  return Array.isArray(value) ? [...value] : value
}

function serializeStructuredConditions() {
  return structuredConditions.value.map((condition) => ({
    field: condition.field,
    op: condition.op,
    value: cloneConditionValue(condition.value),
    value2: cloneConditionValue(condition.value2),
  }))
}

function readSavedConditionStrategies() {
  try {
    const raw = window.localStorage.getItem(SAVED_FILTERS_KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function persistSavedConditionStrategies() {
  try {
    window.localStorage.setItem(SAVED_FILTERS_KEY, JSON.stringify(savedConditionStrategies.value))
  } catch {
    saveConditionError.value = '浏览器本地存储不可用，暂时无法保存策略'
  }
}

function saveCurrentConditionsAsStrategy() {
  saveConditionError.value = ''
  if (!structuredConditions.value.length) {
    saveConditionError.value = '请先添加至少一个条件'
    return
  }
  let normalized
  try {
    normalized = structuredConditions.value.map(normalizeStructuredCondition)
  } catch (err) {
    saveConditionError.value = err.message || '当前条件不完整，不能保存'
    return
  }
  const fallbackName = structuredConditionLabels.value.slice(0, 2).join(' + ') || '自定义条件策略'
  const name = (saveConditionName.value || fallbackName).trim().slice(0, 32)
  const item = {
    id: Date.now().toString(36),
    name,
    conditions: serializeStructuredConditions(),
    normalizedConditions: normalized,
    logic: structuredLogic.value,
    sortBy: structuredSortBy.value,
    sortDesc: structuredSortDesc.value,
    createdAt: Date.now(),
  }
  savedConditionStrategies.value = [item, ...savedConditionStrategies.value.filter((old) => old.name !== name)].slice(0, 12)
  saveConditionName.value = ''
  persistSavedConditionStrategies()
}

function applySavedConditionStrategy(item, options = {}) {
  if (!item?.conditions?.length || isBusy.value) return false
  const silent = options.silent === true
  const baseId = structuredConditionId
  workspaceMode.value = 'structured'
  structuredConditions.value = item.conditions.map((condition, index) => normalizeRestoredCondition({
    ...condition,
    id: baseId + index + 1,
    value: cloneConditionValue(condition.value),
    value2: cloneConditionValue(condition.value2),
  }))
  structuredConditionId = baseId + item.conditions.length
  structuredLogic.value = ['AND', 'OR'].includes(item.logic) ? item.logic : 'AND'
  structuredSortBy.value = typeof item.sortBy === 'string' ? item.sortBy : ''
  structuredSortDesc.value = item.sortDesc !== false
  structuredResult.value = null
  result.value = null
  selectedRowKeys.value = []
  structuredError.value = ''
  errorMsg.value = ''
  activeSavedConditionId.value = item.id
  persistState()
  if (!silent) toast.info(`已载入：${item.name}`)
  return true
}

async function runSavedConditionStrategy(item) {
  if (!applySavedConditionStrategy(item, { silent: true })) return
  await runStructuredScreen()
}

function deleteSavedConditionStrategy(id) {
  savedConditionStrategies.value = savedConditionStrategies.value.filter((item) => item.id !== id)
  if (activeSavedConditionId.value === id) activeSavedConditionId.value = ''
  persistSavedConditionStrategies()
}

function savedConditionSummary(item) {
  const labels = (item.conditions || [])
    .map((condition) => formatStructuredCondition(condition))
    .slice(0, 3)
  return labels.join(' / ') || '条件组合'
}

function savedConditionMeta(item) {
  const logic = item.logic === 'OR' ? '满足任一' : '全部满足'
  const count = item.conditions?.length || 0
  const sortField = item.sortBy ? (fieldLabelMap.value[item.sortBy] || item.sortBy) : '默认排序'
  const sortDirection = item.sortBy ? (item.sortDesc === false ? '升序' : '降序') : ''
  return `${logic} · ${count} 个条件 · ${sortField}${sortDirection}`
}

function formatSavedTime(ts) {
  const time = Number(ts)
  if (!Number.isFinite(time)) return ''
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return ''
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${mm}/${dd}`
}

function mapScreenRows(items, labels) {
  return items.map((item) => {
    const metrics = {
      市盈率: item.pe,
      市净率: item.pb,
      净资产收益率: item.roe,
      市值: item.market_cap,
      股息率: item.dividend_yield,
      换手率: item.turnover,
      风险: item.risk_flag,
      '5日均线': item.ma5,
      '20日均线': item.ma20,
      '20日放量': item.volume_ratio_20,
      '20日涨幅': item.pct_change_20,
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

function syncSelectedRows() {
  const visibleCodes = new Set(rows.value.map((item) => item?.code).filter(Boolean))
  selectedRowKeys.value = selectedRowKeys.value.filter((code) => visibleCodes.has(code) && !wl.has(code))
}

function handleSelectedRowKeys(keys) {
  selectedRowKeys.value = keys
}

function addSelectedRowsToWatchlist() {
  if (!auth.token) {
    toast.info('登录后可以保存自选股')
    router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }
  if (!selectedRows.value.length) {
    toast.info('先勾选要加入自选的股票')
    return
  }
  const candidates = selectedWatchCandidates.value
  if (!candidates.length) {
    toast.info('已选股票已在自选中')
    return
  }
  candidates.forEach((item) => {
    wl.add({
      code: item.code,
      name: item.name,
      sector: item.industry,
      refPrice: item.close,
    })
  })
  toast.success(`已加入自选 ${candidates.length} 只`)
  syncSelectedRows()
}

function setWorkspaceMode(mode) {
  if (!['structured', 'strategy'].includes(mode) || mode === workspaceMode.value || isBusy.value) return
  workspaceMode.value = mode
  selectedRowKeys.value = []
  errorMsg.value = ''
  structuredError.value = ''
  if (mode === 'strategy') {
    structuredResult.value = null
  } else {
    result.value = null
  }
  persistState()
}

const columns = [
  {
    type: 'selection',
    key: 'selection',
    width: 42,
    disabled: (row) => wl.has(row.code),
  },
  {
    title: '股票',
    key: 'stock',
    width: 180,
    render(row) {
      return h('div', { class: 'stock-cell' }, [
        h('div', { class: 'stock-title-row' }, [
          h(StarButton, {
            stock: { code: row.code, name: row.name, sector: row.industry, refPrice: row.close },
            size: 13,
          }),
          h('button', {
            class: 'stock-link',
            onClick: () => gotoDetail(row.code),
          }, row.name || row.code),
        ]),
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
  if (key === '股息率' || key === '净资产收益率' || key === '换手率' || key === '20日涨幅') return `${number.toFixed(2)}%`
  if (key === '20日放量') return `${number.toFixed(2)}x`
  if (key === '风险') return number === 0 ? '普通' : 'ST/退市'
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
  if (!structuredConditions.value.length) {
    structuredError.value = '请先添加至少一个条件'
    return
  }
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
    structuredConditions.value = saved.structuredConditions.map(normalizeRestoredCondition)
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

function normalizeRestoredCondition(condition) {
  if (condition?.field !== 'industry') return condition
  const values = normalizeIndustryValues(condition.value)
  return {
    ...condition,
    value: condition.op === 'in' ? values : (values[0] || null),
  }
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

    const strategyFromQuery = route.query.strategy
    if (strategyFromQuery && templates.value.some((item) => item.id === strategyFromQuery)) {
      workspaceMode.value = 'strategy'
      structuredResult.value = null
      result.value = null
      activeId.value = strategyFromQuery
      runSelection(strategyFromQuery)
    }

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

async function loadIndustries() {
  industryLoading.value = true
  try {
    industryOptions.value = await fetchIndustries()
  } catch (err) {
    industryOptions.value = []
  } finally {
    industryLoading.value = false
  }
}

onMounted(() => {
  savedConditionStrategies.value = readSavedConditionStrategies()
  bootstrap()
  loadIndustries()
})

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

watch(rows, syncSelectedRows)
watch(() => wl.items.map((item) => item.code).join('|'), syncSelectedRows)
</script>

<template>
  <Shell>
    <div class="strategy-page">
      <section class="page-head">
        <h1>策略选股</h1>
      </section>

      <n-card size="small" :bordered="false" class="workspace-card">
        <div class="workspace-bar">
          <n-radio-group :value="workspaceMode" size="small" :disabled="isBusy" @update:value="setWorkspaceMode">
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
            <n-button size="small" secondary :disabled="isBusy" @click="addStructuredCondition">添加条件</n-button>
          </div>

          <div class="condition-builder">
            <div v-if="!structuredConditions.length" class="condition-empty">
              暂无条件
            </div>
            <div v-for="(condition, index) in structuredConditions" :key="condition.id" class="condition-row">
              <span class="condition-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <n-select
                :value="condition.field"
                :options="structuredFieldOptions"
                size="small"
                :disabled="isBusy"
                @update:value="updateStructuredField(condition, $event)"
              />
              <n-select
                :value="condition.op"
                :options="getStructuredOperatorOptions(condition)"
                size="small"
                :disabled="isBusy"
                @update:value="updateStructuredOperator(condition, $event)"
              />
              <n-select
                v-if="isIndustryCondition(condition)"
                class="condition-value-control"
                v-model:value="condition.value"
                :options="industrySelectOptions"
                :multiple="condition.op === 'in'"
                filterable
                clearable
                size="small"
                :loading="industryLoading"
                :disabled="isBusy || industryLoading"
                :placeholder="industryLoading ? '加载行业列表' : (condition.op === 'in' ? '选择一个或多个行业' : '选择行业')"
              />
              <n-input
                v-else-if="getStructuredField(condition.field)?.data_type === 'text'"
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
                :disabled="isBusy"
                @click="removeStructuredCondition(condition.id)"
              >
                删除
              </n-button>
            </div>
          </div>

          <div class="condition-action-row">
            <div class="condition-save-panel">
              <div class="condition-save-title">
                <strong>保存当前条件</strong>
                <span>保存当前条件组合，后续可从下方快速载入和执行</span>
              </div>
              <div class="condition-save-bar">
                <n-input
                  v-model:value="saveConditionName"
                  size="small"
                  maxlength="32"
                  placeholder="策略名，例如：低估值高ROE"
                  :disabled="isBusy"
                />
                <n-button size="small" secondary :disabled="isBusy || !structuredConditions.length" @click="saveCurrentConditionsAsStrategy">
                  保存为策略
                </n-button>
              </div>
              <n-alert v-if="saveConditionError" type="warning" :bordered="false" class="notice compact">
                {{ saveConditionError }}
              </n-alert>
            </div>

            <div class="structured-foot">
              <div>
                <n-tag v-for="label in structuredConditionLabels" :key="label" size="small" :bordered="false">
                  {{ label }}
                </n-tag>
              </div>
              <n-button type="primary" size="small" strong :disabled="isBusy || !structuredConditions.length" :loading="structuredLoading" @click="runStructuredScreen">
                执行筛选
              </n-button>
            </div>
          </div>

          <div class="saved-condition-list">
            <div class="saved-condition-head">
              <div>
                <strong>已保存条件策略</strong>
              </div>
              <n-tag size="small" :bordered="false">{{ savedConditionStrategies.length }} 个</n-tag>
            </div>
            <div v-if="savedConditionStrategies.length" class="saved-condition-grid">
              <div
                v-for="item in savedConditionStrategies"
                :key="item.id"
                class="saved-condition-entry"
                :data-active="item.id === activeSavedConditionId"
              >
                <button
                  type="button"
                  class="saved-condition-card"
                  :disabled="isBusy"
                  @click="applySavedConditionStrategy(item)"
                >
                  <div class="saved-condition-title-row">
                    <strong>{{ item.name }}</strong>
                    <span v-if="formatSavedTime(item.createdAt)">{{ formatSavedTime(item.createdAt) }}</span>
                  </div>
                  <small>{{ savedConditionSummary(item) }}</small>
                  <span class="saved-condition-meta">{{ savedConditionMeta(item) }}</span>
                  <span class="saved-condition-hover-action">
                    {{ item.id === activeSavedConditionId ? '已选中，点击执行按钮筛选' : '点击选中条件策略' }}
                  </span>
                </button>
                <div class="saved-condition-actions">
                  <n-button
                    class="saved-condition-run"
                    size="tiny"
                    secondary
                    type="primary"
                    :disabled="isBusy"
                    @click="runSavedConditionStrategy(item)"
                  >
                    执行
                  </n-button>
                  <n-button
                    class="saved-condition-delete"
                    size="tiny"
                    text
                    type="error"
                    :disabled="isBusy"
                    @click="deleteSavedConditionStrategy(item.id)"
                  >
                    删除
                  </n-button>
                </div>
              </div>
            </div>
            <n-empty v-else size="small" description="还没有保存的条件策略" />
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
            <span class="strategy-item-body">
              <strong>{{ tpl.name }}</strong>
              <small>{{ tpl.description }}</small>
              <ul v-if="tpl.id === activeId" class="strategy-rules-inline">
                <li v-for="rule in tpl.rules" :key="rule">{{ rule }}</li>
              </ul>
            </span>
            <n-tag size="small" :bordered="false">{{ tpl.tag }}</n-tag>
          </button>
          <div class="strategy-action">
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
        <n-card size="small" :bordered="false">
          <template #header>
            <div class="table-head">
              <div>
                <strong>{{ displayTitle }}</strong>
                <span v-if="hasResult">{{ displayTotal }} 只命中</span>
                <span v-else-if="tableLoading">请稍候，正在计算</span>
              </div>
              <div class="table-head-actions">
                <div v-if="workspaceMode === 'structured'" class="result-sort-control">
                  <span>结果排序</span>
                  <n-select v-model:value="structuredSortBy" :options="structuredSortOptions" size="small" :disabled="isBusy" />
                  <n-button size="small" secondary :disabled="isBusy" @click="structuredSortDesc = !structuredSortDesc">
                    {{ structuredSortDesc ? '降序' : '升序' }}
                  </n-button>
                  <n-button size="small" secondary :disabled="isBusy || !structuredConditions.length" :loading="structuredLoading" @click="runStructuredScreen">
                    应用排序
                  </n-button>
                </div>
                <n-button
                  v-if="hasResult && rows.length"
                  size="small"
                  secondary
                  :disabled="tableLoading || !selectedWatchCandidates.length"
                  @click="addSelectedRowsToWatchlist"
                >
                  {{ batchWatchLabel }}
                </n-button>
                <n-tag :bordered="false" size="small" :type="resultSourceType">
                  {{ resultSourceLabel }}
                </n-tag>
              </div>
            </div>
          </template>

          <n-data-table
            v-if="rows.length"
            :columns="displayColumns"
            :data="rows"
            :row-key="(row) => row.code"
            :checked-row-keys="selectedRowKeys"
            :loading="tableLoading"
            :pagination="{ pageSize: 20 }"
            size="small"
            striped
            @update:checked-row-keys="handleSelectedRowKeys"
          />
          <n-empty
            v-else-if="!tableLoading"
            :description="hasResult ? '当前条件没有命中股票' : '请选择策略或输入条件'"
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
  gap: 20px;
}

.page-head,
.workspace-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
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
  border-radius: 10px;
  background: #F7F7F7;
}

.workspace-card :deep(.n-card__content),
.result-panel :deep(.n-card__content) {
  padding: 20px 24px 24px;
}

.workspace-card :deep(.n-card-header),
.result-panel :deep(.n-card-header) {
  padding: 18px 22px 10px;
}

.workspace-bar {
  padding-bottom: 14px;
  border-bottom: 1px solid #EDEDED;
}

.mode-panel {
  padding-top: 14px;
}

.strategy-picker {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding-top: 14px;
}

.details-panel {
  margin-top: 14px;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
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
  gap: 16px;
  justify-content: space-between;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
  background: #FAFAFA;
}

.structured-control {
  gap: 10px;
}

.condition-save-bar {
  display: grid;
  grid-template-columns: minmax(180px, 280px) auto;
  gap: 10px;
  align-items: center;
  margin-top: 10px;
}

.condition-builder {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.condition-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 54px;
  border: 1px dashed #D4D4D8;
  border-radius: 8px;
  background: #FAFAFA;
  color: #71717A;
  font-size: 12px;
}

.condition-row {
  display: grid;
  grid-template-columns: 28px 142px 112px minmax(160px, 1fr) auto auto;
  gap: 10px;
  min-width: 0;
  padding: 10px 10px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
  background: #FFFFFF;
}

.condition-index {
  color: #A1A1AA;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
}

.condition-value-control {
  min-width: 0;
}

.condition-value-control :deep(.n-base-selection-tags) {
  flex-wrap: wrap;
  max-width: 100%;
}

.condition-action-row {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr);
  gap: 12px;
  align-items: stretch;
  margin-top: 14px;
}

.condition-save-panel,
.condition-action-row .structured-foot {
  min-width: 0;
  padding: 12px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
  background: #FAFAFA;
}

.condition-save-title {
  display: grid;
  gap: 3px;
}

.condition-save-title strong {
  color: #111111;
  font-size: 12px;
}

.condition-save-title span {
  color: #71717A;
  font-size: 11px;
}

.saved-condition-list {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
  background: #FFFFFF;
}

.saved-condition-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  color: #71717A;
  font-size: 12px;
  font-weight: 700;
}

.saved-condition-head > div {
  display: grid;
  gap: 3px;
}

.saved-condition-head strong {
  color: #111111;
  font-size: 12px;
}

.saved-condition-head span {
  color: #71717A;
  font-size: 11px;
  font-weight: 500;
}

.saved-condition-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.saved-condition-entry {
  position: relative;
  display: grid;
  gap: 10px;
  align-items: stretch;
  min-width: 0;
  padding: 10px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
  background: #FAFAFA;
  transition: border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.saved-condition-entry:hover,
.saved-condition-entry:focus-within,
.saved-condition-entry[data-active="true"] {
  border-color: #111111;
  background: #FFFFFF;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
}

.saved-condition-entry[data-active="true"] {
  background: #FAFAFA;
}

.saved-condition-card {
  display: grid;
  gap: 4px;
  min-width: 0;
  width: 100%;
  border: 0;
  background: transparent;
  padding: 0;
  color: #3F3F46;
  text-align: left;
  cursor: pointer;
}

.saved-condition-card:disabled {
  cursor: wait;
  opacity: 0.62;
}

.saved-condition-card:focus-visible {
  outline: 2px solid #99F6E4;
  outline-offset: 3px;
  border-radius: 5px;
}

.saved-condition-card strong,
.saved-condition-card small,
.saved-condition-meta,
.saved-condition-hover-action {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.saved-condition-card strong {
  color: #111111;
  font-size: 12px;
}

.saved-condition-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.saved-condition-title-row span {
  flex: 0 0 auto;
  color: #A1A1AA;
  font-size: 10px;
  font-weight: 600;
}

.saved-condition-card small,
.saved-condition-meta {
  color: #71717A;
  font-size: 11px;
}

.saved-condition-hover-action {
  color: #0F766E;
  font-size: 11px;
  font-weight: 700;
  opacity: 0;
  transform: translateY(2px);
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.saved-condition-entry:hover .saved-condition-hover-action,
.saved-condition-entry:focus-within .saved-condition-hover-action {
  opacity: 1;
  transform: translateY(0);
}

.saved-condition-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  opacity: 0;
  transform: translateY(2px);
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.saved-condition-entry:hover .saved-condition-actions,
.saved-condition-entry:focus-within .saved-condition-actions {
  opacity: 1;
  transform: translateY(0);
}

.structured-foot {
  margin-top: 0;
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
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
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

.strategy-item .strategy-item-body {
  flex: 1;
  min-width: 0;
}

.strategy-rules-inline {
  margin: 8px 0 0;
  padding-left: 16px;
  color: #71717A;
  font-size: 11px;
  line-height: 1.6;
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
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
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
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.table-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.table-head span {
  margin-left: 10px;
  color: #71717A;
  font-size: 12px;
}

.result-sort-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 4px;
  border: 1px solid #EDEDED;
  border-radius: 8px;
  background: #FAFAFA;
}

.result-sort-control > span {
  margin: 0 4px 0 2px;
  color: #71717A;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.result-sort-control :deep(.n-select) {
  width: 138px;
}

.stock-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stock-title-row {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.stock-link {
  min-width: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  padding: 0;
  color: #111111;
  font-weight: 700;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.result-panel :deep(.n-data-table-td) {
  padding: 18px 14px;
}

.result-panel :deep(.n-data-table-th) {
  background: transparent;
  color: #71717A;
  font-size: 12px;
  font-weight: 600;
}

.result-panel :deep(.n-data-table-tr:hover td) {
  background: #FFFFFF;
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

  .saved-condition-entry,
  .saved-condition-actions,
  .saved-condition-hover-action {
    transition: none;
  }
}

@media (max-width: 960px) {
  .structured-toolbar,
  .structured-foot {
    align-items: flex-start;
    flex-direction: column;
  }

  .condition-action-row,
  .condition-save-bar,
  .saved-condition-grid {
    grid-template-columns: 1fr;
  }

  .result-sort-control {
    width: 100%;
    flex-wrap: wrap;
  }

  .result-sort-control :deep(.n-select) {
    flex: 1;
    min-width: 132px;
    width: auto;
  }

  .condition-row {
    grid-template-columns: 24px minmax(0, 1fr) minmax(0, 0.9fr);
  }

  .condition-row :deep(.n-input),
  .condition-row :deep(.n-input-number),
  .condition-row .condition-value-control {
    grid-column: 2 / span 2;
    width: 100%;
  }

}

@media (hover: none) {
  .saved-condition-actions,
  .saved-condition-hover-action {
    opacity: 1;
    transform: none;
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

  .table-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .table-head-actions {
    width: 100%;
    justify-content: space-between;
  }

  .result-sort-control {
    justify-content: flex-start;
  }
}
</style>
