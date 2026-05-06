import client from './client'

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

/** 自然语言筛选（千问） */
export async function screenNL(query) {
  const { data } = await client.post('/screener/nl', { query })
  return data
}
