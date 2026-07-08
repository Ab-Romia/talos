const BASE_URL = ''

// --- Session token (Bearer) --------------------------------------------------
// This backend returns the session as an `X-Session-Token` response header for
// API/fetch requests (it only sets a cookie for text/html browser navigations,
// and that cookie is Secure-only so it won't work over http://localhost). So we
// capture that token and send it back as `Authorization: Bearer` on subsequent
// requests. Persisted to localStorage so a page reload stays signed in.
const TOKEN_KEY = 'talos_token'
let sessionToken = localStorage.getItem(TOKEN_KEY) || null

export function setSessionToken(token) {
  sessionToken = token || null
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}
export function getSessionToken() {
  return sessionToken
}
function captureSessionToken(res) {
  const t = res.headers.get('X-Session-Token')
  if (t) setSessionToken(t)
}

// A user-safe fallback for an HTTP status, used whenever the server didn't
// return a clean human-readable message. Never surface raw status text, HTML
// error pages, or internal payloads to the user.
function friendlyForStatus(status) {
  if (status >= 500 || status === 0) return 'Something went wrong. Please try again.'
  if (status === 401) return 'Your session has expired. Please sign in again.'
  if (status === 403) return 'You don’t have permission to do that.'
  if (status === 404) return 'We couldn’t find what you were looking for.'
  if (status === 429) return 'Too many requests — please slow down and try again.'
  return 'Something went wrong. Please try again.'
}

// FastAPI errors come back as {detail: "..."} (HTTPException) OR
// {detail: [{type, loc, msg, input}, ...]} (422 validation). Always reduce to a
// human-readable string so it can be safely rendered in the UI (never an object,
// raw JSON, or internal payload).
function normalizeDetail(detail, fallback) {
  if (detail == null) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (typeof d === 'string') return d
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x) => x !== 'body').join('.') : ''
        return loc && d?.msg ? `${loc}: ${d.msg}` : (d?.msg || '')
      })
      .filter(Boolean)
    return parts.length ? parts.join('; ') : fallback
  }
  if (typeof detail === 'object') return detail.msg || detail.message || fallback
  return fallback
}

async function request(path, options = {}) {
  const { body, method = 'GET', headers = {}, formData } = options

  const config = {
    method,
    credentials: 'include',
    headers: {
      ...(!formData && { 'Content-Type': 'application/json' }),
      ...(sessionToken && { Authorization: `Bearer ${sessionToken}` }),
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
  captureSessionToken(res)

  if (!res.ok) {
    const payload = await res.json().catch(() => ({}))
    const fallback = friendlyForStatus(res.status)
    // keep the raw payload under `errors` for field-level handling, but always
    // expose `detail` as a user-safe string. 5xx bodies are never surfaced
    // verbatim — they get a generic message.
    const detail = res.status >= 500 ? fallback : normalizeDetail(payload.detail, fallback)
    throw { status: res.status, ...payload, errors: payload.detail, detail }
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
      if (value == null) continue
      if (Array.isArray(value)) {
        for (const item of value) formData.append(key, item)
      } else {
        formData.append(key, value)
      }
    }
    return request(path, {
      method: 'POST',
      formData,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  },
  putForm: (path, data) => {
    const formData = new URLSearchParams()
    for (const [key, value] of Object.entries(data)) {
      if (value == null) continue
      if (Array.isArray(value)) {
        for (const item of value) formData.append(key, item)
      } else {
        formData.append(key, value)
      }
    }
    return request(path, { method: 'PUT', formData })
  },
  upload: (path, formData) => request(path, { method: 'POST', formData }),
  putQuery: (path, params) => {
    const query = new URLSearchParams(params).toString()
    return request(`${path}?${query}`, { method: 'PUT' })
  },
  // POST that tolerates a success redirect (e.g. /signup/complete returns a 302).
  // Resolves true on any 2xx (without parsing the body), throws normalized on error.
  postAllowRedirect: async (path, body) => {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(sessionToken && { Authorization: `Bearer ${sessionToken}` }),
      },
      body: JSON.stringify(body),
    })
    captureSessionToken(res)
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      const fallback = friendlyForStatus(res.status)
      const detail = res.status >= 500 ? fallback : normalizeDetail(payload.detail, fallback)
      throw { status: res.status, ...payload, errors: payload.detail, detail }
    }
    return true
  },
}
