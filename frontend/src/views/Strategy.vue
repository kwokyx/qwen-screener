<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDivider,
  NEmpty,
  NGrid,
  NGridItem,
  NInput,
  NNumberAnimation,
  NSkeleton,
  NSpace,
  NTag,
} from 'naive-ui'
import Shell from '../components/Shell.vue'
import { getStrategyTemplates, runStrategyAgent, selectStrategy } from '../api/strategy'
import { useAiStatusStore } from '../stores/aiStatus'

const router = useRouter()
const aiStatus = useAiStatusStore()

const templates = ref([])
const activeId = ref('')
const result = ref(null)
const agentResult = ref(null)
const agentQuery = ref('低估值高分红的银行股')
const loading = ref(false)
const agentLoading = ref(false)
const errorMsg = ref('')
const agentError = ref('')

const activeTemplate = computed(() => templates.value.find((item) => item.id === activeId.value))
const rows = computed(() => {
  const screen = agentResult.value?.screen_result
  if (screen?.items?.length) {
    return screen.items.map((item) => ({
      ...item,
      score: null,
      signals: agentResult.value?.plan?.conditions?.map((cond) => `${cond.field} ${cond.op} ${Array.isArray(cond.value) ? cond.value.join('-') : cond.value}`) || ['条件筛选'],
      metrics: {
        PE: item.pe,
        PB: item.pb,
        ROE: item.roe,
        市值: item.market_cap,
        股息率: item.dividend_yield,
      },
    }))
  }
  return agentResult.value?.strategy_result?.items || result.value?.items || []
})
const displayTotal = computed(() => agentResult.value?.screen_result?.total ?? agentResult.value?.strategy_result?.total ?? result.value?.total ?? 0)
const displayTradeDate = computed(() => agentResult.value?.strategy_result?.trade_date || result.value?.trade_date || '-')
const displayTitle = computed(() => {
  if (agentResult.value) return `Agent：${agentResult.value.plan?.tool_label || '智能选股'}`
  return activeTemplate.value?.name || '策略'
})

const summary = computed(() => {
  const list = rows.value
  const up = list.filter((item) => (item.change_pct || 0) > 0).length
  const scoreItems = list.filter((item) => typeof item.score === 'number')
  const avgScore = scoreItems.length ? scoreItems.reduce((sum, item) => sum + item.score, 0) / scoreItems.length : 0
  return [
    { label: '命中股票', value: displayTotal.value, suffix: '只' },
    { label: '当前显示', value: list.length, suffix: '只' },
    { label: '上涨占比', value: list.length ? Math.round(up / list.length * 100) : 0, suffix: '%' },
    { label: '平均得分', value: Number(avgScore.toFixed(1)), suffix: '' },
  ]
})

const agentExamples = [
  '低估值高分红的银行股',
  '找最近强势突破的股票',
  '半导体行业里的大市值龙头',
  '白马股，ROE 高，估值不要太贵',
]

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
    title: '信号',
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
      return h('div', { class: 'metrics-line' }, Object.entries(row.metrics || {}).map(([key, value]) => `${key}: ${value}`).join(' / ') || '-')
    },
  },
]

async function runSelection(id = activeId.value) {
  if (!id) return
  loading.value = true
  errorMsg.value = ''
  agentResult.value = null
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

function useExample(text) {
  agentQuery.value = text
  runAgent()
}

async function bootstrap() {
  loading.value = true
  aiStatus.startAutoProbe()
  try {
    templates.value = await getStrategyTemplates()
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
          <div class="agent-answer">{{ agentResult.answer }}</div>
          <div class="agent-meta">
            <n-tag size="small" :bordered="false">{{ agentResult.plan.tool_label }}</n-tag>
            <n-tag size="small" :bordered="false" :type="agentResult.plan.ai_used ? 'success' : 'warning'">
              {{ agentResult.plan.ai_used ? 'AI 已参与规划' : '本地规则规划' }}
            </n-tag>
            <span>{{ agentResult.plan.reasoning }}</span>
          </div>
          <n-alert v-if="agentResult.warnings?.length" type="warning" :bordered="false" class="notice compact">
            <div v-for="warning in agentResult.warnings" :key="warning">{{ warning }}</div>
          </n-alert>
          <n-divider />
          <div class="tool-trace">
            <span>工具调用</span>
            <code v-for="trace in agentResult.tool_trace" :key="trace">{{ trace }}</code>
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
              <n-number-animation :from="0" :to="item.value" />
              <span>{{ item.suffix }}</span>
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
                <n-tag :bordered="false" type="success">{{ agentResult ? 'Agent 工具结果' : (activeTemplate?.source || '本地策略') }}</n-tag>
              </div>
            </template>

            <n-data-table
              v-if="rows.length"
              :columns="columns"
              :data="rows"
              :loading="loading"
              :pagination="{ pageSize: 20 }"
              size="small"
              striped
            />
            <n-empty v-else-if="!loading" description="当前策略没有命中股票" />
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

.agent-answer {
  font-size: 13px;
  color: #111111;
  line-height: 1.65;
  font-weight: 650;
}

.agent-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.tool-trace {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tool-trace > span {
  color: #111111;
  font-weight: 700;
}

.tool-trace code {
  padding: 3px 6px;
  border-radius: 4px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  color: #3F3F46;
  font-size: 11px;
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

  .agent-shell,
  .agent-input {
    grid-template-columns: 1fr;
  }
}
</style>
