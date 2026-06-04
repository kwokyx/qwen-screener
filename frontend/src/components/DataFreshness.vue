<script setup>
// 数据新鲜度指示 + 手动同步面板
// - 收起态：一个小标签显示 "数据：今日 / 1天前 / N天前"
// - 展开态：覆盖率 + 可手动触发的后台同步任务

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { A2 } from '../shared/theme.js'
import { dataHealth, triggerSync } from '../api/health'
import { toast } from '../stores/toast'
import { friendlyError } from '../shared/errors.js'
import { useAuthStore } from '../stores/auth'
import Icon from './Icon.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const open = ref(false)
const meta = ref({})            // sync_meta
const counts = ref(null)        // {basic, daily, financial, with_industry}
const coverage = ref(null)
const latestDate = ref(null)
const expectedDate = ref(null)
const fresh = ref(false)
const freshness = ref(null)
const warnings = ref([])
const loading = ref(false)
const running = ref({})         // {jobName: boolean}
const canSync = computed(() => Boolean(auth.token))
const hasSyncIssue = computed(() => warnings.value.length > 0)
const syncWarningsDataAvailable = computed(() =>
  hasSyncIssue.value && warnings.value.every((w) => w.can_fast_retry || w.data_impact === 'data_available')
)
const hasIssue = computed(() => {
  const code = freshness.value?.reason_code
  return (hasSyncIssue.value && !syncWarningsDataAvailable.value) || ['empty_basic', 'empty_daily', 'sync_issue', 'stale'].includes(code)
})
let poller = null

const JOBS = [
  { name: 'daily_market',           label: '日线行情',   desc: '最新交易日行情覆盖', eta: '后台约数分钟' },
  { name: 'daily_value',            label: '估值数据',   desc: '估值、市值、股息率补全', eta: '后台约数分钟' },
  { name: 'weekly_fundamentals',    label: '财务指标',   desc: 'ROE、营收、净利等指标', eta: '后台耗时较长' },
  { name: 'weekly_dividend',        label: '分红数据',   desc: '现金分红与股息率重算', eta: '后台耗时较长' },
  { name: 'weekly_basic',           label: '股票列表',   desc: '全 A 股代码列表更新', eta: '后台约十几秒' },
  { name: 'weekly_kline_backfill',  label: 'K线回填',    desc: '补齐近期历史 K 线', eta: '后台耗时较长' },
  { name: 'db_backup',              label: '数据备份',   desc: '备份当前本地数据库', eta: '后台约数秒' },
]

async function refresh() {
  loading.value = true
  try {
    const r = await dataHealth()
    meta.value = r.sync_meta || {}
    counts.value = r.counts
    coverage.value = r.coverage
    latestDate.value = r.latest_trade_date
    expectedDate.value = r.expected_trade_date
    fresh.value = !!r.fresh
    freshness.value = r.freshness || null
    warnings.value = Array.isArray(r.sync_warnings) ? r.sync_warnings : []
  } catch (e) {
    /* 静默 */
  } finally {
    loading.value = false
  }
}

async function runJob(name) {
  if (!canSync.value) {
    router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }
  if (running.value[name]) return
  running.value[name] = true
  toast.info(`${labelOf(name)} 正在提交后台同步...`)
  try {
    const r = await triggerSync(name)
    if (r.meta) {
      meta.value = { ...meta.value, [name]: r.meta }
    }
    if (r.running) {
      toast.info(`${labelOf(name)} 已在后台执行中`)
    } else if (r.queued || r.meta?.status === 'queued') {
      toast.success(`${labelOf(name)} 已排队，稍后自动更新状态`)
    } else if (r.meta?.status === 'success') {
      toast.success(`${labelOf(name)} 已完成`)
    } else if (r.meta?.status === 'failed') {
      toast.error(`${labelOf(name)} 失败：${r.meta?.detail || '请稍后重试'}`)
    } else {
      toast.info(`${labelOf(name)} 状态已更新`)
    }
    await refresh()
  } catch (e) {
    toast.error(friendlyError(e))
  } finally {
    running.value[name] = false
  }
}

function labelOf(name) {
  return JOBS.find((j) => j.name === name)?.label || name
}

function statusOf(name) {
  if (running.value[name]) return 'queued'
  return meta.value[name]?.display_status || (meta.value[name]?.stuck ? 'stuck' : meta.value[name]?.status) || ''
}

function isJobActive(name) {
  return ['queued', 'running'].includes(statusOf(name))
}

function statusLabel(status) {
  if (status === 'queued') return '已排队'
  if (status === 'running') return '执行中'
  if (status === 'stuck') return '异常'
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  return '未执行'
}

function statusStyle(status) {
  if (status === 'failed' || status === 'stuck') return { background: A2.upSoft, color: A2.up }
  if (status === 'queued' || status === 'running') return { background: A2.amberSoft, color: A2.amber }
  if (status === 'success') return { background: A2.downSoft, color: A2.down }
  return { background: A2.bgDeep, color: A2.textDim }
}

function pct(value) {
  if (value == null) return '—'
  return `${Math.round(Number(value) * 100)}%`
}

function shortDate(value) {
  if (!value) return ''
  return String(value).slice(5)
}

function fmtRel(iso) {
  if (!iso) return '从未'
  const parsed = parseServerUtcTime(iso)
  const t = parsed.getTime()
  const diff = (Date.now() - t) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return parsed.toLocaleDateString('zh-CN')
}

function parseServerUtcTime(value) {
  const text = String(value || '').trim()
  if (!text) return new Date(Number.NaN)
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(text)) return new Date(text)
  return new Date(`${text.replace(' ', 'T')}Z`)
}

function taskMetaLine(name) {
  const lastRun = fmtRel(meta.value[name]?.last_run_at)
  const duration = meta.value[name]?.duration_ms
    ? ` · 耗时 ${(meta.value[name].duration_ms / 1000).toFixed(0)}s`
    : ''
  const covered = latestDate.value && fresh.value ? `数据覆盖至 ${latestDate.value} · ` : ''
  return `${covered}任务更新 ${lastRun}${duration}`
}

const summary = computed(() => {
  if (freshness.value?.reason_code === 'fresh') return { label: '已最新', tone: 'fresh' }
  if (freshness.value?.reason_code === 'partial_newer_data') return { label: `至 ${shortDate(latestDate.value)}`, tone: 'meh' }
  if (freshness.value?.label) return { label: freshness.value.label, tone: freshness.value.severity || (fresh.value ? 'fresh' : 'stale') }
  if (!latestDate.value) return { label: '加载中', tone: 'muted' }
  const d = new Date(latestDate.value)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((today - d) / 86400000)
  if (days <= 0) return { label: '今日', tone: 'fresh' }
  if (days === 1) return { label: '昨日', tone: 'fresh' }
  if (days <= 3) return { label: `${days} 天前`, tone: 'meh' }
  return { label: `${days} 天前`, tone: 'stale' }
})

const summaryColor = computed(() =>
  hasIssue.value ? A2.up :
  hasSyncIssue.value ? A2.amber :
  summary.value.tone === 'fresh' ? A2.down :
  summary.value.tone === 'meh' ? A2.amber :
  summary.value.tone === 'stale' ? A2.up :
  A2.textMuted
)

const activeJobLabels = computed(() =>
  (freshness.value?.active_jobs || []).map(labelOf).join('、')
)

const recommendedJobLabels = computed(() =>
  (freshness.value?.recommended_jobs || []).map(labelOf).join('、')
)

const warningJobLabels = computed(() =>
  warnings.value.map((w) => w.label || labelOf(w.job)).filter(Boolean).join('、')
)

const activeSyncJobs = computed(() =>
  JOBS.filter((j) => isJobActive(j.name)).map((j) => j.name)
)

const activeSyncJobLabels = computed(() =>
  activeSyncJobs.value.map(labelOf).join('、')
)

const retryableWarnings = computed(() =>
  JOBS
    .map((j) => warnings.value.find((w) => w.job === j.name))
    .filter((w) => {
      if (!w?.job) return false
      const status = statusOf(w.job) || w.status
      return ['failed', 'stuck'].includes(status)
    })
)

const nextRetryWarning = computed(() => retryableWarnings.value[0] || null)
const nextRetryJob = computed(() => nextRetryWarning.value?.job || '')
const nextRetryJobLabel = computed(() => nextRetryJob.value ? labelOf(nextRetryJob.value) : '')
const retryButtonLabel = computed(() =>
  nextRetryWarning.value?.can_fast_retry ? '修复下一个异常状态' : '重试下一个异常'
)

const retryWarningMessage = computed(() => {
  if (!retryableWarnings.value.length) return ''
  if (activeSyncJobLabels.value) return `已有同步任务执行中：${activeSyncJobLabels.value}。完成后再重试异常任务。`
  if (nextRetryWarning.value?.can_fast_retry) {
    return `将修复 ${nextRetryJobLabel.value} 的异常状态；数据已达标时不会重新拉取全市场。`
  }
  return `将先重试 ${nextRetryJobLabel.value}，其余异常任务请等待当前任务完成后再继续。`
})

const syncImpactMessage = computed(() => {
  if (!hasSyncIssue.value) return ''
  const warningJobs = new Set(warnings.value.map((w) => w.job))
  if (fresh.value) {
    if (syncWarningsDataAvailable.value) {
      return '数据当前可用，行情已达到应有交易日；这些异常来自上次后台任务中断，登录后可按顺序修复状态。'
    }
    if (warningJobs.has('daily_market') || warningJobs.has('daily_value')) {
      return '行情日期已达到应有交易日，但行情或估值同步任务仍有异常；涉及价格、估值或股息率的筛选建议先重试对应任务。'
    }
    return '行情日期已达到应有交易日；这些异常主要影响财务、分红或历史 K 线等补充数据，基础行情筛选仍可用。'
  }
  return '行情尚未达到应有交易日且存在同步异常；请先重试异常任务，再查看新鲜度是否恢复。'
})

const syncNextStepMessage = computed(() => {
  if (warningJobLabels.value) {
    if (retryableWarnings.value.length && retryableWarnings.value.every((w) => w.can_fast_retry)) return `下一步：修复 ${warningJobLabels.value} 的异常状态。`
    return `下一步：重试 ${warningJobLabels.value}。`
  }
  if (recommendedJobLabels.value) return `下一步：运行 ${recommendedJobLabels.value}。`
  return ''
})

function warningFor(name) {
  return warnings.value.find((w) => w.job === name)
}

function actionLabelFor(name) {
  if (isJobActive(name)) return '后台执行'
  return warningFor(name)?.can_fast_retry ? '修复状态' : '立即同步'
}

function close() {
  open.value = false
}

function goLogin() {
  router.push({ name: 'login', query: { redirect: route.fullPath } })
}

async function retryNextWarningJob() {
  if (!canSync.value) {
    goLogin()
    return
  }
  if (activeSyncJobLabels.value) {
    toast.info(`已有同步任务执行中：${activeSyncJobLabels.value}`)
    return
  }
  if (!nextRetryJob.value) {
    toast.info('当前没有可重试的异常任务')
    return
  }
  await runJob(nextRetryJob.value)
}
function onDoc(e) {
  if (!open.value) return
  if (!e.target.closest('[data-data-freshness]')) close()
}

onMounted(() => {
  refresh()
  poller = window.setInterval(refresh, 12000)
  document.addEventListener('mousedown', onDoc)
})
onBeforeUnmount(() => {
  if (poller) window.clearInterval(poller)
  document.removeEventListener('mousedown', onDoc)
})
</script>

<template>
  <div data-data-freshness :style="{ position: 'relative' }">
    <button @click="open = !open"
            :title="`数据更新于 ${latestDate || '未知'}，点击查看详情`"
            :style="{ display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '4px 9px', background: 'transparent', border: `1px solid ${A2.borderHair}`, borderRadius: '999px', fontSize: '10.5px', cursor: 'pointer', color: A2.textSub, fontFamily: 'IBM Plex Mono, monospace', height: '24px' }">
      <span :style="{ width: '6px', height: '6px', borderRadius: '50%', background: summaryColor, display: 'inline-block' }" />
      数据 {{ summary.label }}
    </button>

    <Transition name="page-fade">
      <div v-if="open" :style="{ position: 'absolute', top: '32px', right: 0, width: 'min(380px, calc(100vw - 24px))', background: A2.surface, borderRadius: '10px', boxShadow: A2.shadowLg, border: `1px solid ${A2.borderHair}`, zIndex: 50, overflow: 'hidden' }">
        <div :style="{ padding: '12px 14px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
          <div>
            <div :style="{ fontSize: '13px', fontWeight: 700 }">数据状态</div>
            <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginTop: '2px' }">
              <span v-if="latestDate">最新 <strong :style="{ color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ latestDate }}</strong><span v-if="expectedDate"> · 应至 {{ expectedDate }}</span></span>
              <span v-else>未同步</span>
            </div>
            <div v-if="freshness?.message" :style="{ fontSize: '10.5px', color: A2.textSub, marginTop: '5px', lineHeight: 1.45, maxWidth: '300px' }">
              {{ freshness.message }}
            </div>
          </div>
          <button class="btn-ghost" :style="{ width: '28px', height: '28px' }" @click="refresh" title="刷新状态">
            <Icon name="refresh" :size="13" :style="{ animation: loading ? 'spin 1s linear infinite' : 'none' }" />
          </button>
        </div>

        <!-- 数据覆盖度 -->
        <div v-if="counts" :style="{ padding: '10px 14px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(72px, 1fr))', gap: '8px', borderBottom: `1px solid ${A2.borderHair}`, background: '#FBFBF9' }">
          <div v-for="c in [
            { l: '日线覆盖', v: pct(coverage?.latest_daily) },
            { l: '估值覆盖', v: pct(coverage?.latest_valuation) },
            { l: '财务覆盖', v: pct(coverage?.financial) },
            { l: '股息覆盖', v: pct(coverage?.latest_dividend_yield) },
          ]" :key="c.l" :style="{ textAlign: 'center' }">
            <div :style="{ fontSize: '9.5px', color: A2.textMuted, fontWeight: 600, letterSpacing: '0.4px' }">{{ c.l }}</div>
            <div :style="{ fontSize: '14px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: A2.text, marginTop: '2px' }">{{ c.v }}</div>
          </div>
        </div>

        <div v-if="freshness && freshness.reason_code !== 'fresh'" :style="{ padding: '10px 14px', borderBottom: `1px solid ${A2.borderHair}`, background: freshness.severity === 'stale' ? A2.upSoft : A2.amberSoft }">
          <div :style="{ fontSize: '11px', fontWeight: 700, color: freshness.severity === 'stale' ? A2.up : A2.amber, marginBottom: '4px' }">新鲜度诊断</div>
          <div :style="{ fontSize: '10.5px', color: A2.textSub, lineHeight: 1.55 }">
            全市场覆盖 {{ freshness.latest_coverage_rows || 0 }} / {{ counts?.basic || 0 }}，达标阈值 {{ freshness.coverage_threshold || counts?.market_coverage_threshold || 0 }}。
            <span v-if="freshness.lag_days != null">落后 {{ Math.max(freshness.lag_days, 0) }} 个自然日。</span>
          </div>
          <div v-if="activeJobLabels" :style="{ fontSize: '10.5px', color: A2.textSub, lineHeight: 1.55, marginTop: '3px' }">
            后台执行中：{{ activeJobLabels }}
          </div>
          <div v-if="recommendedJobLabels" :style="{ fontSize: '10.5px', color: A2.textSub, lineHeight: 1.55, marginTop: '3px' }">
            建议同步：{{ recommendedJobLabels }}
          </div>
        </div>

        <div v-if="hasSyncIssue" :style="{ padding: '10px 14px', borderBottom: `1px solid ${A2.borderHair}`, background: A2.upSoft }">
          <div :style="{ fontSize: '11px', fontWeight: 700, color: A2.up, marginBottom: '4px' }">同步异常</div>
          <div v-if="syncImpactMessage" :style="{ fontSize: '10.5px', color: A2.textSub, lineHeight: 1.55, marginBottom: '4px' }">
            {{ syncImpactMessage }}
          </div>
          <div v-for="w in warnings.slice(0, 3)" :key="w.job" :style="{ fontSize: '10.5px', color: A2.textSub, lineHeight: 1.55 }">
            {{ w.label }}：{{ w.message || '任务异常，请重试' }}<span v-if="w.can_fast_retry">（数据已达标）</span>
            <div v-if="w.recommended_action" :style="{ color: A2.textDim }">建议：{{ w.recommended_action }}</div>
          </div>
          <div v-if="syncNextStepMessage" :style="{ fontSize: '10.5px', color: A2.up, lineHeight: 1.55, marginTop: '4px', fontWeight: 600 }">
            {{ syncNextStepMessage }}
          </div>
          <div v-if="retryWarningMessage" :style="{ fontSize: '10.5px', color: A2.textSub, lineHeight: 1.55, marginTop: '4px' }">
            {{ retryWarningMessage }}
          </div>
          <button v-if="canSync && retryableWarnings.length"
                  class="btn-outline"
                  :disabled="Boolean(activeSyncJobLabels) || !nextRetryJob"
                  :title="activeSyncJobLabels ? '已有同步任务执行中' : '按顺序重试，避免并发重任务'"
                  :style="{ marginTop: '8px', padding: '5px 9px', fontSize: '11px', background: A2.surface, maxWidth: '100%' }"
                  @click="retryNextWarningJob">
            <Icon name="refresh" :size="11" :style="{ animation: activeSyncJobLabels ? 'spin 1s linear infinite' : 'none' }" />
            {{ retryButtonLabel }}
          </button>
        </div>

        <div v-if="!canSync" :style="{ padding: '12px 14px', borderTop: `1px solid ${A2.borderHair}` }">
          <div :style="{ fontSize: '11.5px', color: A2.textSub, lineHeight: 1.6, marginBottom: '10px' }">
            数据状态可公开查看。手动同步需要登录后执行，避免误触发耗时任务。
          </div>
          <button class="btn-outline" :style="{ padding: '6px 10px', fontSize: '11px' }" @click="goLogin">
            登录后同步
          </button>
        </div>

        <!-- 任务列表 -->
        <div v-else :style="{ padding: '6px 0', maxHeight: '380px', overflowY: 'auto' }">
          <div v-for="j in JOBS" :key="j.name" :style="{ padding: '10px 14px', borderTop: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', gap: '10px' }">
            <div :style="{ flex: 1, minWidth: 0 }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
                <span :style="{ fontSize: '12px', fontWeight: 600, color: A2.text }">{{ j.label }}</span>
                <span :style="{ fontSize: '9px', padding: '1px 5px', borderRadius: '3px', fontWeight: 700, ...statusStyle(statusOf(j.name)) }">{{ statusLabel(statusOf(j.name)) }}</span>
              </div>
              <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ j.desc }}</div>
              <div :style="{ fontSize: '10px', color: A2.textDim, marginTop: '2px', fontFamily: 'IBM Plex Mono, monospace', lineHeight: 1.35 }">
                {{ taskMetaLine(j.name) }}
              </div>
              <div v-if="['failed', 'stuck'].includes(statusOf(j.name)) && meta[j.name]?.detail" :style="{ fontSize: '10px', color: A2.up, marginTop: '3px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">
                {{ meta[j.name].detail }}
              </div>
            </div>
            <button @click="runJob(j.name)" :disabled="isJobActive(j.name)"
                    :title="`预计 ${j.eta}`"
                    class="btn-outline" :style="{ padding: '5px 10px', fontSize: '11px', whiteSpace: 'nowrap', minWidth: '64px' }">
              <Icon name="refresh" :size="11" :style="{ animation: isJobActive(j.name) ? 'spin 1s linear infinite' : 'none' }" />
              {{ actionLabelFor(j.name) }}
            </button>
          </div>
        </div>

        <div :style="{ padding: '8px 14px', fontSize: '10.5px', color: A2.textDim, lineHeight: 1.5, background: '#FBFBF9', borderTop: `1px solid ${A2.borderHair}` }">
          自动同步按交易日和周末任务执行；任务更新时间不是行情日期，以上方“最新”交易日和覆盖率为准。
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
</style>
