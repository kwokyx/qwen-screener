import client from './client'

export async function getStrategyTemplates() {
  const { data } = await client.get('/strategy/templates')
  return data
}

export async function selectStrategy(strategyId, opts = {}) {
  const { data } = await client.post('/strategy/select', {
    strategy_id: strategyId,
    limit: opts.limit || 50,
  })
  return data
}

export async function runStrategyAgent(query, opts = {}) {
  const { data } = await client.post('/strategy/agent', {
    query,
    limit: opts.limit || 50,
  })
  return data
}
