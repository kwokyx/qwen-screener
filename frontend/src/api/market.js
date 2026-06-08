import client from './client'

const MARKET_TIMEOUT_MS = 12_000

export async function indices() {
  const { data } = await client.get('/market/indices', { timeout: MARKET_TIMEOUT_MS })
  return data
}

export async function sectors(limit = 8) {
  const { data } = await client.get('/market/sectors', { params: { limit }, timeout: MARKET_TIMEOUT_MS })
  return data
}

export async function industries() {
  const { data } = await client.get('/market/industries', { timeout: MARKET_TIMEOUT_MS })
  return data
}

export async function movers(limit = 8) {
  const { data } = await client.get('/market/movers', { params: { limit }, timeout: MARKET_TIMEOUT_MS })
  return data
}

export async function ticker() {
  const { data } = await client.get('/market/ticker', { timeout: MARKET_TIMEOUT_MS })
  return data
}
