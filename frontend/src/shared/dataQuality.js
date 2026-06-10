export const screeningQualityFields = [
  { key: 'pe', label: '市盈率' },
  { key: 'pb', label: '市净率' },
  { key: 'roe', label: '净资产收益率' },
  { key: 'market_cap', label: '市值' },
  { key: 'dividend_yield', label: '股息率' },
]

export const detailQualityFields = [
  { key: 'trade_date', label: '交易日' },
  { key: 'close', label: '收盘价' },
  { key: 'pe', label: '市盈率' },
  { key: 'pb', label: '市净率' },
  { key: 'market_cap', label: '市值' },
  { key: 'dividend_yield', label: '股息率' },
  { key: 'roe', label: '净资产收益率' },
  { key: 'profit_yoy', label: '净利同比' },
]

export function isMissingValue(value) {
  if (value === null || value === undefined || value === '') return true
  if (typeof value === 'number') return !Number.isFinite(value)
  return false
}

export function qualityForRecord(record, fields = screeningQualityFields) {
  const missing = fields.filter((field) => isMissingValue(record?.[field.key]))
  const present = fields.length - missing.length
  const ratio = fields.length ? present / fields.length : 1
  return {
    total: fields.length,
    present,
    ratio,
    missing,
    missingLabels: missing.map((field) => field.label),
    tagType: ratio >= 0.9 ? 'success' : ratio >= 0.65 ? 'warning' : 'error',
  }
}

export function summarizeQuality(records, fields = screeningQualityFields) {
  const rows = Array.isArray(records) ? records : []
  const fieldStats = fields.map((field) => {
    const present = rows.filter((row) => !isMissingValue(row?.[field.key])).length
    const ratio = rows.length ? present / rows.length : 1
    return { ...field, present, total: rows.length, ratio }
  })
  const totalSlots = rows.length * fields.length
  const presentSlots = fieldStats.reduce((sum, field) => sum + field.present, 0)
  const ratio = totalSlots ? presentSlots / totalSlots : 1
  const weakFields = fieldStats.filter((field) => field.ratio < 1)
  return {
    total: totalSlots,
    present: presentSlots,
    ratio,
    fields: fieldStats,
    weakFields,
  }
}

export function formatCoverage(value) {
  if (!Number.isFinite(value)) return '—'
  return `${Math.round(value * 100)}%`
}

export function detailQualityRecord(detail, quote = null) {
  const latest = detail?.latest || {}
  const q = quote || {}
  return {
    trade_date: latest.trade_date,
    close: q.close ?? latest.close,
    pe: q.pe ?? latest.pe,
    pb: q.pb ?? latest.pb,
    market_cap: q.market_cap ?? latest.market_cap,
    dividend_yield: latest.dividend_yield,
    turnover: q.turnover ?? latest.turnover,
    roe: detail?.roe,
    revenue_yoy: detail?.revenue_yoy,
    profit_yoy: detail?.profit_yoy,
    gross_margin: detail?.gross_margin,
    debt_ratio: detail?.debt_ratio,
  }
}
