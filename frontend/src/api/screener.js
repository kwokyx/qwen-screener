import client from './client'
import { streamSSE } from './sse'

/**
 * 结构化筛选
 * @param {Array<{field:string, op:string, value:any}>} conditions
 * @param {object} opts { logic, sort_by, sort_desc, offset, limit }
 */
export async function screen(conditions, opts = {}) {
  const { data } = await client.post('/screener', {
    conditions,
    logic: opts.logic || 'AND',
    sort_by: opts.sort_by,
    sort_desc: opts.sort_desc !== false,
    offset: opts.offset || 0,
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
 * 自然语言筛选（流式 bounded ReAct）。
 * 事件 type:
 *   'thinking'          公开进度文本
 *   'planning'          Agent 计划元数据
 *   'react_step'        模型选择下一步
 *   'tool_start'        本地工具开始执行
 *   'tool_observation'  工具 observation 摘要
 *   'tool_done'         工具执行完成
 *   'final'             ReAct 最终回答步骤
 *   'parsed'            筛选参数校验完成，payload.conditions 是结构化条件数组
 *   'planned'   策略工具已确定，准备执行
 *   'screening' 引擎正在执行
 *   'result'    最终结果，payload = { items, total, parsed_conditions }
 *   'done'      流结束
 *   'error'     payload.message
 */
export function streamNL(query, onEvent, signal, context = null) {
  return streamSSE('/api/v1/screener/nl/stream', {
    method: 'POST',
    body: context ? { query, context } : { query },
    onEvent,
    signal,
  })
}
