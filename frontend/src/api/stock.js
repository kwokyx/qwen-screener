import client from './client'

export async function search(q, limit = 20) {
  const { data } = await client.get('/stock/search', { params: { q, limit } })
  return data
}

export async function detail(code) {
  const { data } = await client.get(`/stock/${code}`)
  return data
}

export async function quote(code) {
  const { data } = await client.get(`/stock/${code}/quote`)
  return data
}

export async function kline(code, days = 120, frequency = 'd') {
  const { data } = await client.get(`/stock/${code}/kline`, { params: { days, frequency } })
  return data
}

export async function intraday(code, frequency = '5', days = 1) {
  const { data } = await client.get(`/stock/${code}/intraday`, { params: { frequency, days } })
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

/**
 * upsert：服务端把已有行的 alerts / note / ref_price 改成传入值；
 * stores/watchlist.js 在登录态下每次本地变更后调用，把"该 code 的最新状态"推回去。
 */
export async function upsertWatch(code, { note = null, alerts = null, refPrice = null } = {}) {
  const { data } = await client.post('/stock/me/watchlist', {
    code,
    note,
    alerts,
    ref_price: refPrice,
  })
  return data
}

export async function removeWatch(code) {
  await client.delete(`/stock/me/watchlist/${code}`)
}
