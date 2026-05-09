// 预警轮询引擎
//
// 思路：每 N 秒拉一次每只自选股的最新价（GET /api/v1/stock/{code}），
// 把 {code, close, open, prevClose} 喂给 watchlist.evaluateAlerts，触发的写入 notifications。
//
// 默认严格模式：真实行情拉不到就跳过，不假报价、不触发假告警。
// 仅在 URL 带 ?demo=1 时进入"模拟行情"——以加入价为基准 ±1.5% 高斯抖动，
// 用于不开服务时的原型演示。

import { useWatchlistStore } from '../stores/watchlist'
import { useNotificationsStore } from '../stores/notifications'
import * as stockApi from '../api/stock'

const POLL_MS = 30_000          // 真实数据 30s 一次（不烧 API）
const DEMO_TICK_MS = 8_000      // demo 模式 8s 一次

let timer = null
let demoMode = false

function gaussian() {
  // Box–Muller
  let u = 0, v = 0
  while (u === 0) u = Math.random()
  while (v === 0) v = Math.random()
  return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v)
}

// 给每只 demo 股票一个独立的"游走价格" cache
const demoPriceCache = new Map()
function demoQuote(item) {
  const base = item.refPrice || 100
  const cached = demoPriceCache.get(item.code)
  const last = cached ?? base
  // 每 tick ±1.5% 高斯游走，但回归到 base
  const drift = (base - last) * 0.05
  const noise = gaussian() * base * 0.015
  const next = Math.max(0.01, last + drift + noise)
  demoPriceCache.set(item.code, next)
  return { close: next, open: base, prevClose: base }
}

async function fetchQuote(code) {
  try {
    const d = await stockApi.detail(code)
    const l = d.latest || {}
    return {
      close: l.close ?? null,
      open: l.open ?? null,
      prevClose: l.prev_close ?? null,
    }
  } catch (e) {
    // 后端没数据：默认 quote=null（不告警），仅在 ?demo=1 时切到游走价格驱动告警
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('demo')) {
      demoMode = true
    }
    return null
  }
}

async function tick() {
  const wl = useWatchlistStore()
  const notif = useNotificationsStore()
  if (!wl.items.length) return

  for (const item of wl.items) {
    let quote
    if (demoMode) {
      quote = demoQuote(item)
    } else {
      quote = await fetchQuote(item.code)
      if (!quote) continue   // 没真实行情就跳过这只，不再合成假报价触发告警
    }

    const fired = wl.evaluateAlerts(item.code, quote)
    for (const f of fired) {
      const tone = f.alert.type.includes('down') || f.alert.type === 'price_lt' ? 'down' : 'up'
      notif.push({
        kind: 'alert',
        tone,
        tag: alertTag(f.alert),
        stock: item.name || item.code,
        code: item.code,
        desc: f.detail,
      })
      wl.markTriggered(item.code, f.alert.id)
    }
  }
}

function alertTag(a) {
  switch (a.type) {
    case 'pct_up':   return `涨幅 ≥${a.threshold}%`
    case 'pct_down': return `跌幅 ≥${Math.abs(a.threshold)}%`
    case 'price_gt': return `价格突破 ${a.threshold}`
    case 'price_lt': return `价格跌破 ${a.threshold}`
    case 'day_pct':  return `日内 ${a.threshold > 0 ? '+' : ''}${a.threshold}%`
    default:         return '预警'
  }
}

export function startAlertEngine() {
  if (timer) return
  // 立即跑一次，再设定 interval
  tick().catch(() => {})
  timer = setInterval(() => {
    tick().catch(() => {})
  }, demoMode ? DEMO_TICK_MS : POLL_MS)
}

export function stopAlertEngine() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

export function isDemoMode() {
  return demoMode
}
