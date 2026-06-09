import * as stockApi from '../api/stock'

function calcChangePct(close, prevClose) {
  if (close == null || !prevClose) return null
  return (close - prevClose) / prevClose * 100
}

function quoteSourceMeta(source, hasLocal) {
  if (source === 'tencent') {
    return {
      label: '实时',
      title: '来自实时行情 provider',
    }
  }
  if (source === 'local' || hasLocal) {
    return {
      label: '日线',
      title: '实时行情不可用或超时，当前使用本地最新日线',
    }
  }
  return { label: '', title: '' }
}

export function normalizeStockSnapshot(code, detail = null, quote = null) {
  const latest = detail?.latest || null
  const display = quote || latest || null
  const close = display?.close ?? latest?.close ?? null
  const prevClose = display?.prev_close ?? detail?.prev_close ?? null
  const change = display?.change ?? (close != null && prevClose ? close - prevClose : null)
  const changePct = display?.change_pct ?? detail?.change_pct ?? calcChangePct(close, prevClose)
  const source = quote?.source || (latest ? 'local' : null)
  const sourceMeta = quoteSourceMeta(source, Boolean(latest))

  return {
    code,
    name: quote?.name || detail?.name || code,
    industry: detail?.industry || null,
    detail,
    quote,
    close,
    prev_close: prevClose,
    change,
    change_pct: changePct,
    open: display?.open ?? latest?.open ?? null,
    high: display?.high ?? latest?.high ?? null,
    low: display?.low ?? latest?.low ?? null,
    volume: display?.volume ?? latest?.volume ?? null,
    turnover: display?.turnover ?? latest?.turnover ?? null,
    pe: display?.pe ?? latest?.pe ?? null,
    pb: display?.pb ?? latest?.pb ?? null,
    market_cap: display?.market_cap ?? latest?.market_cap ?? null,
    dividend_yield: latest?.dividend_yield ?? null,
    trade_date: quote?.quote_time || latest?.trade_date || null,
    source,
    source_label: sourceMeta.label,
    source_title: sourceMeta.title,
  }
}

export async function fetchStockSnapshot(code) {
  const [detailResult, quoteResult] = await Promise.allSettled([
    stockApi.detail(code),
    stockApi.quote(code),
  ])
  const detail = detailResult.status === 'fulfilled' ? detailResult.value : null
  const quote = quoteResult.status === 'fulfilled' ? quoteResult.value : null
  if (!detail && !quote) throw new Error(`无法加载 ${code}`)
  return normalizeStockSnapshot(code, detail, quote)
}

export async function fetchWatchSnapshots(items) {
  const results = await Promise.allSettled(items.map((item) => fetchStockSnapshot(item.code)))
  const map = {}
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') map[items[index].code] = result.value
  })
  return map
}
