import client from './client'

export async function login(username, password) {
  // FastAPI OAuth2PasswordRequestForm 要求 form-encoded
  const form = new URLSearchParams({ username, password })
  const { data } = await client.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return data
}

export async function register(username, password, email) {
  const { data } = await client.post('/auth/register', { username, password, email })
  return data
}

export async function me() {
  const { data } = await client.get('/auth/me')
  return data
}
