/** 筛选 / 条件选股页共用的字段中文名与选项 */

export const POOL_OPTIONS = [
  { value: 'all', label: '全 A 股' },
  { value: 'csi300', label: '沪深 300' },
  { value: 'csi500', label: '中证 500' },
  { value: 'sse50', label: '上证 50' },
]

export const EXTRA_FIELD_OPTIONS = [
  { field: 'pb', label: '市净率 PB' },
  { field: 'turnover', label: '换手率 (%)' },
  { field: 'close', label: '现价 (元)' },
  { field: 'gross_margin', label: '毛利率 (%)' },
  { field: 'debt_ratio', label: '负债率 (%)' },
  { field: 'revenue_yoy', label: '营收同比增长 (%)' },
  { field: 'profit_yoy', label: '净利润同比增长 (%)' },
]

export const OP_OPTIONS = [
  { value: 'gt', label: '>' },
  { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '≤' },
  { value: 'between', label: '区间' },
]

/** 页顶一句话说明 */
export const SCREENER_INTRO =
  '用市盈率、市值、盈利能力等指标，从股票池里筛出符合要求的股票；勾选并填写数字后点「应用筛选」即可。'

export const FIELD_LABEL_MAP = {
  pe: '市盈率 (TTM)',
  pb: '市净率 PB',
  roe: 'ROE（净资产收益率）',
  market_cap: '市值 (亿)',
  dividend_yield: '股息率 (%)',
  revenue_yoy: '营收同比增长 (%)',
  profit_yoy: '净利润同比增长 (%)',
  gross_margin: '毛利率 (%)',
  debt_ratio: '负债率 (%)',
  turnover: '换手率 (%)',
  close: '现价 (元)',
  industry: '行业',
}

const OP_LABEL = Object.fromEntries(OP_OPTIONS.map((o) => [o.value, o.label]))

export function fieldLabel(field) {
  return FIELD_LABEL_MAP[field] || field
}

export function opLabel(op) {
  return OP_LABEL[op] || op
}
