import client from './client'
import { streamSSE } from './sse'

/**
 * 结构化筛选
 * @param {Array<{field:string, op:string, value:any}>} conditions
 * @param {object} opts { logic, sort_by, sort_desc, limit }
 */
export async function screen(conditions, opts = {}) {
  const { data } = await client.post('/screener', {
    conditions,
    logic: opts.logic || 'AND',
    sort_by: opts.sort_by,
    sort_desc: opts.sort_desc !== false,
    limit: opts.limit || 50,
  })
  return data
}

/** 自然语言筛选（千问，一次性返回） */
export async function screenNL(query) {
  const { data } = await client.post('/screener/nl', { query })
  return data
}

/**
 * 自然语言筛选（流式）。
 * 事件 type:
 *   'thinking'  千问正在生成结构化条件，payload.text 是 token
 *   'parsed'    解析完成，payload.conditions 是结构化条件数组
 *   'screening' 引擎正在执行
 *   'result'    最终结果，payload = { items, total, parsed_conditions }
 *   'done'      流结束
 *   'error'     payload.message
 */
export function streamNL(query, onEvent, signal) {
  return streamSSE('/api/v1/screener/nl/stream', {
    method: 'POST',
    body: { query },
    onEvent,
    signal,
  })
}
