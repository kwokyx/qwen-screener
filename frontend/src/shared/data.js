// Shared mock data ported from prototype

export const STOCKS = [
  { code: '300750', name: '宁德时代', price: 235.80, change: 4.32, changePct: 1.87, pe: 28.4, pb: 4.2, mcap: 10380, vol: 8.2, sector: '电池', bull: 92, ai: '机构持仓显著增加，业绩超预期，新订单饱满' },
  { code: '002594', name: '比亚迪', price: 268.40, change: 6.80, changePct: 2.60, pe: 22.1, pb: 3.8, mcap: 7820, vol: 6.5, sector: '汽车', bull: 88, ai: '海外销量翻倍，欧洲市场拓展顺利' },
  { code: '688981', name: '中芯国际', price: 78.32, change: 2.15, changePct: 2.82, pe: 45.2, pb: 2.9, mcap: 6240, vol: 5.1, sector: '半导体', bull: 85, ai: '先进制程产能持续提升，国产替代加速' },
  { code: '600519', name: '贵州茅台', price: 1682.50, change: -8.30, changePct: -0.49, pe: 24.3, pb: 8.1, mcap: 21130, vol: 1.2, sector: '白酒', bull: 76, ai: '渠道库存健康，但短期消费复苏不及预期' },
  { code: '000858', name: '五粮液', price: 158.20, change: -1.20, changePct: -0.75, pe: 18.6, pb: 4.5, mcap: 6140, vol: 2.1, sector: '白酒', bull: 72, ai: '估值已回到合理区间，等待消费回暖信号' },
  { code: '601318', name: '中国平安', price: 52.30, change: 0.45, changePct: 0.87, pe: 8.2, pb: 0.9, mcap: 9520, vol: 3.4, sector: '保险', bull: 68, ai: '高股息策略受机构青睐，寿险新单回暖' },
  { code: '300760', name: '迈瑞医疗', price: 285.60, change: 5.40, changePct: 1.93, pe: 32.5, pb: 7.2, mcap: 3460, vol: 1.8, sector: '医疗器械', bull: 81, ai: '海外市场拓展顺利，第三季度业绩超预期' },
  { code: '002415', name: '海康威视', price: 36.85, change: 0.92, changePct: 2.56, pe: 25.8, pb: 4.1, mcap: 3420, vol: 4.2, sector: '安防', bull: 74, ai: 'AI视觉新业务增速较快，但需关注海外限制' },
  { code: '688256', name: '寒武纪', price: 542.30, change: 28.50, changePct: 5.55, pe: -85.2, pb: 12.4, mcap: 2260, vol: 12.5, sector: 'AI芯片', bull: 79, ai: '国产AI算力需求旺盛，但高估值需警惕' },
  { code: '600036', name: '招商银行', price: 38.60, change: -0.20, changePct: -0.52, pe: 6.8, pb: 0.85, mcap: 9740, vol: 2.8, sector: '银行', bull: 71, ai: '高股息+低估值组合，适合稳健配置' },
]

export const SECTORS = [
  { name: '半导体', change: 3.42, count: 156, hot: 'AI算力需求' },
  { name: '新能源车', change: 2.18, count: 88, hot: '海外销量超预期' },
  { name: '医疗器械', change: 1.85, count: 124, hot: '集采落地' },
  { name: '电池', change: 1.62, count: 67, hot: '原材料价格回升' },
  { name: '人工智能', change: 4.21, count: 92, hot: '大模型应用落地' },
  { name: '白酒', change: -0.82, count: 32, hot: '消费复苏待验证' },
  { name: '银行', change: -0.31, count: 42, hot: '净息差承压' },
  { name: '地产', change: -1.42, count: 78, hot: '政策预期反复' },
]

export const INDICES = [
  { name: '上证指数', code: 'SH000001', value: 3186.42, change: 18.32, changePct: 0.58 },
  { name: '深证成指', code: 'SZ399001', value: 10524.18, change: 86.45, changePct: 0.83 },
  { name: '创业板指', code: 'SZ399006', value: 2148.62, change: 31.20, changePct: 1.47 },
  { name: '科创50', code: 'SH000688', value: 962.45, change: 14.32, changePct: 1.51 },
]

// seed-based deterministic random so re-renders don't reshuffle visuals
function mulberry32(seed) {
  let a = seed
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function genKline(base, days, volatility = 0.02, seed = 1) {
  const rand = mulberry32(seed)
  const data = []
  let price = base
  for (let i = 0; i < days; i++) {
    const o = price
    const change = (rand() - 0.48) * volatility * price
    const c = o + change
    const h = Math.max(o, c) + rand() * 0.005 * price
    const l = Math.min(o, c) - rand() * 0.005 * price
    const v = Math.floor(rand() * 800000) + 200000
    data.push({ o, c, h, l, v, day: i })
    price = c
  }
  return data
}

export function seededRand(seed) {
  return mulberry32(seed)
}
