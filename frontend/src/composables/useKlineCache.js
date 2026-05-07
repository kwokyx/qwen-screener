import { ref } from 'vue'
import { kline as fetchKline } from '../api/stock.js'

/**
 * 多个 view 共享的 sparkline kline 缓存。
 * - 按 code 缓存 close 数组，避免重复拉取
 * - 并行请求；单只失败不影响其它
 * 用法：
 *   const { cache, load, get } = useKlineCache(30)
 *   load(['600519.SH', '000001.SZ'])
 *   <Sparkline :data="get(code)" />
 */
export function useKlineCache(days = 30) {
  const cache = ref({})  // { code: [closes] }

  async function load(codes) {
    const need = (codes || []).filter((c) => c && !(c in cache.value))
    if (!need.length) return
    const results = await Promise.allSettled(need.map((c) => fetchKline(c, days)))
    const next = { ...cache.value }
    results.forEach((r, i) => {
      next[need[i]] = r.status === 'fulfilled'
        ? (r.value || []).map((d) => d.close).filter((v) => v != null)
        : []
    })
    cache.value = next
  }

  function get(code) {
    return cache.value[code] || []
  }

  return { cache, load, get }
}
