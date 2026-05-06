import client from './client'

export async function indices() {
  const { data } = await client.get('/market/indices')
  return data
}

export async function sectors(limit = 8) {
  const { data } = await client.get('/market/sectors', { params: { limit } })
  return data
}

export async function movers(limit = 8) {
  const { data } = await client.get('/market/movers', { params: { limit } })
  return data
}

export async function ticker() {
  const { data } = await client.get('/market/ticker')
  return data
}
