const BASE_URL = ''

async function request(path, options = {}) {
  const { body, method = 'GET', headers = {}, formData } = options

  const config = {
    method,
    credentials: 'include',
    headers: {
      ...(!formData && { 'Content-Type': 'application/json' }),
      ...headers,
    },
  }

  if (body && !formData) {
    config.body = JSON.stringify(body)
  }
  if (formData) {
    config.body = formData
    delete config.headers['Content-Type']
  }

  const res = await fetch(`${BASE_URL}${path}`, config)

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw { status: res.status, ...error }
  }

  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return null
  }

  return res.json()
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body }),
  put: (path, body) => request(path, { method: 'PUT', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  delete: (path) => request(path, { method: 'DELETE' }),
  postForm: (path, data) => {
    const formData = new URLSearchParams()
    for (const [key, value] of Object.entries(data)) {
      formData.append(key, value)
    }
    return request(path, {
      method: 'POST',
      formData,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  },
  putQuery: (path, params) => {
    const query = new URLSearchParams(params).toString()
    return request(`${path}?${query}`, { method: 'PUT' })
  },
}
