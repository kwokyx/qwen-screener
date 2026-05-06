import client from './client'

export async function analyze(code) {
  const { data } = await client.get(`/qwen/analysis/${code}`)
  return data
}
