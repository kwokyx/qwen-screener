import client from './client'

export async function listSessions(limit = 50) {
  const { data } = await client.get('/chat/sessions', { params: { limit } })
  return data
}

export async function createSession(payload) {
  // payload = { query, context_id, parsed_conditions, items, total, screen_meta, agent_* }
  const { data } = await client.post('/chat/sessions', payload)
  return data
}

export async function getSessionByContext(contextId) {
  const { data } = await client.get(`/chat/sessions/context/${encodeURIComponent(contextId)}`)
  return data
}

export async function updateSession(id, payload) {
  const { data } = await client.put(`/chat/sessions/${id}`, payload)
  return data
}

export async function deleteSession(id) {
  await client.delete(`/chat/sessions/${id}`)
}

export async function clearSessions() {
  await client.delete('/chat/sessions')
}
