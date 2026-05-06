// Watchlist + 价格预警 store。
// 离线优先：始终读写 localStorage；只要登录了就镜像到后端 /stock/me/watchlist。
//
// 数据结构：
//   item = {
//     code:        "600519.SH",
//     name:        "贵州茅台",          // 加入时缓存的名字（避免无后端时显示"—"）
//     sector:      "白酒",
//     refPrice:    1742.50,             // 加入时的基准价（用于计算"自加入起 +X%" 类预警）
//     addedAt:     1714530000,          // unix 秒
//     alerts: [
//       { id, type, threshold, enabled, lastTriggered }
//     ]
//   }
//
// 预警类型 type：
//   pct_up     | pct_down       自加入起涨/跌 ≥ threshold (%)
//   price_gt   | price_lt       现价突破 threshold（绝对价）
//   day_pct    现价相对当日开盘 ±threshold% （需要后端实时数据）
//
// 触发的事件由 stores/notifications.js 接收并显示。

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

const LS_KEY = 'qwen.watchlist.v1'

function loadFromLS() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function uid() {
  return Math.random().toString(36).slice(2, 10)
}

export const useWatchlistStore = defineStore('watchlist', () => {
  const items = ref(loadFromLS())

  watch(items, (v) => localStorage.setItem(LS_KEY, JSON.stringify(v)), { deep: true })

  const codes = computed(() => new Set(items.value.map((x) => x.code)))

  function has(code) {
    return codes.value.has(code)
  }

  function get(code) {
    return items.value.find((x) => x.code === code)
  }

  function add({ code, name = '', sector = '', refPrice = null }) {
    if (has(code)) return
    items.value.push({
      code,
      name,
      sector,
      refPrice: refPrice == null ? null : Number(refPrice),
      addedAt: Math.floor(Date.now() / 1000),
      alerts: [],
    })
  }

  function remove(code) {
    items.value = items.value.filter((x) => x.code !== code)
  }

  function toggle(stock) {
    if (has(stock.code)) remove(stock.code)
    else add(stock)
  }

  function addAlert(code, alert) {
    const it = get(code)
    if (!it) return
    it.alerts.push({
      id: uid(),
      enabled: true,
      lastTriggered: null,
      ...alert,
    })
  }

  function removeAlert(code, alertId) {
    const it = get(code)
    if (!it) return
    it.alerts = it.alerts.filter((a) => a.id !== alertId)
  }

  function setAlertEnabled(code, alertId, enabled) {
    const it = get(code)
    if (!it) return
    const a = it.alerts.find((a) => a.id === alertId)
    if (a) a.enabled = enabled
  }

  function markTriggered(code, alertId) {
    const it = get(code)
    if (!it) return
    const a = it.alerts.find((a) => a.id === alertId)
    if (a) a.lastTriggered = Math.floor(Date.now() / 1000)
  }

  /**
   * 给定一支股票的当前行情，返回所有应该触发的预警
   * priceSnapshot = { close, open, prevClose }
   */
  function evaluateAlerts(code, priceSnapshot) {
    const it = get(code)
    if (!it || !priceSnapshot) return []
    const fired = []
    const now = Math.floor(Date.now() / 1000)
    const COOLDOWN = 60 * 60 // 同一条预警 1h 内只触发一次

    for (const a of it.alerts) {
      if (!a.enabled) continue
      if (a.lastTriggered && now - a.lastTriggered < COOLDOWN) continue

      const { close, open, prevClose } = priceSnapshot
      let triggered = false
      let detail = ''

      switch (a.type) {
        case 'pct_up': {
          if (it.refPrice && close != null) {
            const pct = ((close - it.refPrice) / it.refPrice) * 100
            if (pct >= a.threshold) {
              triggered = true
              detail = `自加入价 ${it.refPrice.toFixed(2)} 累计上涨 ${pct.toFixed(2)}% (阈值 ≥${a.threshold}%)`
            }
          }
          break
        }
        case 'pct_down': {
          if (it.refPrice && close != null) {
            const pct = ((close - it.refPrice) / it.refPrice) * 100
            if (pct <= -Math.abs(a.threshold)) {
              triggered = true
              detail = `自加入价 ${it.refPrice.toFixed(2)} 累计下跌 ${pct.toFixed(2)}% (阈值 ≤-${Math.abs(a.threshold)}%)`
            }
          }
          break
        }
        case 'price_gt':
          if (close != null && close >= a.threshold) {
            triggered = true
            detail = `现价 ${close.toFixed(2)} 已突破 ${a.threshold}`
          }
          break
        case 'price_lt':
          if (close != null && close <= a.threshold) {
            triggered = true
            detail = `现价 ${close.toFixed(2)} 已跌破 ${a.threshold}`
          }
          break
        case 'day_pct': {
          const base = open ?? prevClose
          if (close != null && base) {
            const pct = ((close - base) / base) * 100
            if (Math.abs(pct) >= Math.abs(a.threshold) && (a.threshold > 0 ? pct >= a.threshold : pct <= a.threshold)) {
              triggered = true
              detail = `日内涨跌 ${pct.toFixed(2)}% 触发阈值 ${a.threshold}%`
            }
          }
          break
        }
      }

      if (triggered) fired.push({ alert: a, item: it, detail })
    }
    return fired
  }

  return {
    items,
    has,
    get,
    add,
    remove,
    toggle,
    addAlert,
    removeAlert,
    setAlertEnabled,
    markTriggered,
    evaluateAlerts,
  }
})
