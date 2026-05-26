import client from './client'

export async function aiHealth() {
  const { data } = await client.get('/health/ai')
  return data
}

export async function dataHealth() {
  const { data } = await client.get('/health/data')
  return data
}

/**
 * 手动触发同步。
 * @param {string} job daily_market | daily_value | weekly_fundamentals | weekly_basic
 * @param {boolean} wait true 时同步等待任务结束（短任务）；默认 async 立即返回 queued
 */
export async function triggerSync(job, wait = false) {
  const { data } = await client.post(`/health/sync/${job}`, null, {
    timeout: wait ? 600000 : 60000,
    params: wait ? { wait: true } : {},
  })
  return data
}
