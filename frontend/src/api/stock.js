import client from './client'

export async function search(q, limit = 20) {
  const { data } = await client.get('/stock/search', { params: { q, limit } })
  return data
}

export async function detail(code) {
  const { data } = await client.get(`/stock/${code}`)
  return data
}

export async function kline(code, days = 120) {
  const { data } = await client.get(`/stock/${code}/kline`, { params: { days } })
  return data
}

export async function listWatchlist() {
  const { data } = await client.get('/stock/me/watchlist')
  return data
}

export async function addWatch(code, note = null) {
  const { data } = await client.post('/stock/me/watchlist', { code, note })
  return data
}

export async function removeWatch(code) {
  await client.delete(`/stock/me/watchlist/${code}`)
}
