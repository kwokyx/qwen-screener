import client from './client'

export async function aiHealth() {
  const { data } = await client.get('/health/ai', { timeout: 5_000 })
  return data
}

export async function dataHealth() {
  const { data } = await client.get('/health/data', { timeout: 8_000 })
  return data
}

/** 手动触发一次同步：market_refresh / daily_market / daily_value / weekly_fundamentals / weekly_basic */
export async function triggerSync(job) {
  const { data } = await client.post(`/health/sync/${job}`, null, { timeout: 600000 })  // 10 min
  return data
}
