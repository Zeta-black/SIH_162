// All backend access in one place.
//
// The browser never contacts NASA FIRMS or Overpass directly — it only ever
// talks to the FastAPI backend, which holds the FIRMS key server-side. That is
// a hard rule of the project, not a convenience.

const BASE = import.meta.env.VITE_API_BASE ?? ''

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (cause) {
    // Network-level failure: the backend is not running or is unreachable.
    throw new ApiError(
      'Could not reach the FIRETRACE backend. Check that it is running on port 8000.',
      0,
    )
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      // Response body was not JSON; keep the status-based message.
    }
    throw new ApiError(detail, response.status)
  }

  return response.json()
}

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      if (value.length) search.set(key, value.join(','))
      return
    }
    if (typeof value === 'boolean') {
      if (value) search.set(key, 'true')
      return
    }
    search.set(key, String(value))
  })
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export const api = {
  health: () => request('/health'),
  meta: () => request('/api/meta'),
  modelInfo: () => request('/api/model/info'),
  sources: () => request('/api/sources'),
  hotspots: (params, options = {}) => request(`/api/hotspots${query(params)}`, options),
  events: (params) => request(`/api/events${query(params)}`),
  event: (id, params) => request(`/api/events/${encodeURIComponent(id)}${query(params)}`),
  incidents: (params) => request(`/api/incidents${query(params)}`),
  incident: (id) => request(`/api/incidents/${encodeURIComponent(id)}`),
  incidentAction: (id, body) =>
    request(`/api/incidents/${encodeURIComponent(id)}/action`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  hotspot: (id, params) => request(`/api/hotspots/${encodeURIComponent(id)}${query(params)}`),
  facilities: (params, options = {}) => request(`/api/facilities${query(params)}`, options),
  summary: (params) => request(`/api/dashboard/summary${query(params)}`),
  scenarios: () => request('/api/scenarios'),

  // --- Pass 2 -------------------------------------------------------------
  timeline: () => request('/api/timeline'),
  notifications: (params) => request(`/api/notifications${query(params ?? {})}`),
  notificationPolicy: () => request('/api/notifications/policy'),
  notificationAction: (id, body) =>
    request(`/api/notifications/${encodeURIComponent(id)}/action`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  notificationTest: () => request('/api/notifications/test', { method: 'POST' }),
  changes: (since) => request(`/api/changes${query({ since })}`),
  gpkgUrl: (params) => `${BASE}/api/export/gpkg${query(params)}`,
  geojsonLayerUrl: (layer, params) =>
    `${BASE}/api/export/geojson/${layer}${query(params)}`,

  // The main screen is served by exactly one request, so the summary counts,
  // the markers and the provenance chip can never disagree with each other.
  map: (params, options = {}) => request(`/api/map${query(params)}`, options),
  mapSearch: (params) => request(`/api/map/search${query(params)}`),

  // Demo replay. `run` executes the real backend pipeline on a historical
  // case; it is a POST because it writes detections and incidents.
  replayCatalogue: (params) => request(`/api/replay/catalogue${query(params ?? {})}`),
  replayCase: (id) => request(`/api/replay/case/${id}`),
  replayRun: (id, params) =>
    request(`/api/replay/run/${id}${query(params ?? {})}`, { method: 'POST' }),
  classify: (body) =>
    request('/api/classify', { method: 'POST', body: JSON.stringify(body) }),
  refresh: () => request('/api/refresh', { method: 'POST' }),
  jsonUrl: (params) => `${BASE}/api/export/json${query(params)}`,
  geojsonUrl: (params) => `${BASE}/api/export/geojson${query(params)}`,
  csvUrl: (params) => `${BASE}/api/export/csv${query(params)}`,
}

export { ApiError }
