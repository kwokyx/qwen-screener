// Watchlist + 价格预警 store。
// 双向同步策略：
//   - localStorage 始终读写（offline 兜底）
//   - 登录后调 syncFromServer()：服务端列表合并进本地 + 把本地独有的项推上去
//   - 本地任一变更（add / remove / addAlert / removeAlert / setAlertEnabled / batch alert ops）在
//     登录态下都会 push 到后端，失败静默（保持离线可用）
//
// 数据结构：
//   item = {
//     code:        "600519.SH",
//     name:        "贵州茅台",          // 加入时缓存的名字（避免无后端时显示"—"）
//     sector:      "白酒",
//     refPrice:    1742.50,             // 加入时的基准价
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

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import * as stockApi from '../api/stock'

const LS_KEY = 'qwen.watchlist.v1'

function isLoggedIn() {
  return !!localStorage.getItem('token')
}

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

function toUnixSeconds(value) {
  if (!value) return null
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null
    return Math.floor(value > 1e12 ? value / 1000 : value)
  }
  const raw = String(value).trim()
  if (!raw) return null
  const iso = /Z$|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}Z`
  const ms = Date.parse(iso)
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null
}

/** 把 store item 转成 upsert payload。后端用 ref_price，前端 refPrice。 */
function toPayload(item) {
  return {
    note: item.note ?? null,
    alerts: item.alerts ?? [],
    refPrice: item.refPrice ?? null,
  }
}

/** 静默推送当前 item。失败吞掉（offline 时不阻塞 UI）。 */
function pushSilently(item) {
  if (!isLoggedIn() || !item) return
  stockApi.upsertWatch(item.code, toPayload(item)).catch(() => { /* offline 静默 */ })
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
    const item = {
      code,
      name,
      sector,
      refPrice: refPrice == null ? null : Number(refPrice),
      addedAt: Math.floor(Date.now() / 1000),
      alerts: [],
    }
    items.value.push(item)
    pushSilently(item)
  }

  function remove(code) {
    items.value = items.value.filter((x) => x.code !== code)
    if (isLoggedIn()) {
      stockApi.removeWatch(code).catch(() => {})
    }
  }

  /** 登出时调，清掉内存 + localStorage（避免下个账号在同一浏览器登录时混入上个账号数据）。 */
  function clear() {
    items.value = []
  }

  function toggle(stock) {
    if (has(stock.code)) remove(stock.code)
    else add(stock)
  }

  /** 与后端双向同步：服务端 → 本地（覆盖 alerts/refPrice），本地独有 → 推到服务端。 */
  async function syncFromServer() {
    if (!isLoggedIn()) return
    let remote
    try {
      remote = await stockApi.listWatchlist()
    } catch {
      return // 离线/未授权时静默
    }
    if (!Array.isArray(remote)) return

    const remoteByCode = new Map(remote.map((r) => [r.code, r]))
    const localByCode = new Map(items.value.map((x) => [x.code, x]))

    // 服务端有的：以服务端 alerts/refPrice 为准，本地的 name/sector 保留（前端展示需要）
    const merged = []
    for (const r of remote) {
      const local = localByCode.get(r.code)
      merged.push({
        code: r.code,
        name: local?.name || r.name || '',
        sector: local?.sector || '',
        refPrice: r.ref_price ?? local?.refPrice ?? null,
        addedAt: toUnixSeconds(r.created_at) || local?.addedAt || Math.floor(Date.now() / 1000),
        alerts: Array.isArray(r.alerts) ? r.alerts : [],
      })
    }

    // 本地独有的：保留 + 推到服务端
    const localOnly = items.value.filter((x) => !remoteByCode.has(x.code))
    for (const it of localOnly) {
      merged.push(it)
      pushSilently(it)
    }

    items.value = merged
  }

  /** 旧接口名兼容（auth.js 已经调过）：直接转发 syncFromServer。 */
  async function syncFromBackend() {
    return syncFromServer()
  }

  function _pushByCode(code) {
    pushSilently(get(code))
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
    _pushByCode(code)
  }

  function removeAlert(code, alertId) {
    const it = get(code)
    if (!it) return
    it.alerts = it.alerts.filter((a) => a.id !== alertId)
    _pushByCode(code)
  }

  function setAlertEnabled(code, alertId, enabled) {
    const it = get(code)
    if (!it) return
    const a = it.alerts.find((a) => a.id === alertId)
    if (a) {
      a.enabled = enabled
      _pushByCode(code)
    }
  }

  function setAlertsEnabled(code, alertIds, enabled) {
    const it = get(code)
    if (!it) return 0
    const ids = new Set(alertIds)
    let changed = 0
    for (const alert of it.alerts || []) {
      if (!ids.has(alert.id)) continue
      if ((alert.enabled !== false) !== enabled) {
        alert.enabled = enabled
        changed += 1
      }
    }
    if (changed) _pushByCode(code)
    return changed
  }

  function removeAlerts(code, alertIds) {
    const it = get(code)
    if (!it) return 0
    const ids = new Set(alertIds)
    const before = it.alerts?.length || 0
    it.alerts = (it.alerts || []).filter((alert) => !ids.has(alert.id))
    const removed = before - it.alerts.length
    if (removed) _pushByCode(code)
    return removed
  }

  function markTriggered(code, alertId) {
    const it = get(code)
    if (!it) return
    const a = it.alerts.find((a) => a.id === alertId)
    if (a) {
      a.lastTriggered = Math.floor(Date.now() / 1000)
      _pushByCode(code)
    }
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
    clear,
    addAlert,
    removeAlert,
    setAlertEnabled,
    setAlertsEnabled,
    removeAlerts,
    markTriggered,
    evaluateAlerts,
    syncFromServer,
    syncFromBackend,
  }
})
