import { ref } from 'vue'
import { kline as fetchKline } from '../api/stock.js'

/**
 * 多个 view 共享的 sparkline kline 缓存。
 * - 按 code 缓存 close 数组，避免重复拉取
 * - 受控并发请求；单只失败不影响其它
 * 用法：
 *   const { cache, load, get } = useKlineCache(30)
 *   load(['600519.SH', '000001.SZ'])
 *   <Sparkline :data="get(code)" />
 */
export function useKlineCache(days = 30, options = {}) {
  const cache = ref({})  // { code: [closes] }
  const inFlight = new Set()
  const requestedConcurrency = Number(options.concurrency ?? 4)
  const concurrency = Number.isFinite(requestedConcurrency) ? Math.max(1, requestedConcurrency) : 4

  async function load(codes) {
    const seen = new Set()
    const need = (codes || []).filter((c) => {
      if (!c || c in cache.value || inFlight.has(c) || seen.has(c)) return false
      seen.add(c)
      inFlight.add(c)
      return true
    })
    if (!need.length) return

    async function fetchOne(code) {
      try {
        const rows = await fetchKline(code, days)
        cache.value = {
          ...cache.value,
          [code]: (rows || []).map((d) => d.close).filter((v) => v != null),
        }
      } catch {
        cache.value = { ...cache.value, [code]: [] }
      } finally {
        inFlight.delete(code)
      }
    }

    const queue = [...need]
    const workers = Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
      while (queue.length) {
        const code = queue.shift()
        if (code) await fetchOne(code)
      }
    })
    await Promise.all(workers)
  }

  function get(code) {
    return cache.value[code] || []
  }

  return { cache, load, get }
}
