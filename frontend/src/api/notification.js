import client from './client'

export async function listNotifications(limit = 100) {
  const { data } = await client.get('/notifications', { params: { limit } })
  return data
}

export async function createNotification(payload) {
  // payload = { kind, tone, stock_code, title, desc }
  const { data } = await client.post('/notifications', payload)
  return data
}

export async function markRead(id) {
  const { data } = await client.post(`/notifications/${id}/read`)
  return data
}

export async function markAllRead() {
  await client.post('/notifications/read-all')
}

export async function deleteNotification(id) {
  await client.delete(`/notifications/${id}`)
}

export async function clearNotifications() {
  await client.delete('/notifications')
}
