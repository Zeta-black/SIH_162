// Small formatting helpers shared across panels.
//
// Every one of these returns an explicit dash for a missing value rather than
// substituting a zero. "FRP not reported by this product" and "FRP is 0 MW"
// mean different things and the dashboard must not blur them.

export const DASH = '—'

export function num(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return Number(value).toFixed(digits)
}

export function int(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return Number(value).toLocaleString('en-IN')
}

export function pct(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function km(value) {
  if (value === null || value === undefined) return DASH
  const v = Number(value)
  if (v < 1) return `${Math.round(v * 1000)} m`
  return `${v.toFixed(2)} km`
}

export function coords(lat, lon) {
  if (lat === null || lon === null) return DASH
  const ns = lat >= 0 ? 'N' : 'S'
  const ew = lon >= 0 ? 'E' : 'W'
  return `${Math.abs(lat).toFixed(4)}° ${ns}, ${Math.abs(lon).toFixed(4)}° ${ew}`
}

/** FIRMS timestamps are UTC. Indian users read IST, so show both. */
export function utcAndIst(iso) {
  if (!iso) return { utc: DASH, ist: DASH }
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return { utc: DASH, ist: DASH }
  const utc = d.toISOString().slice(0, 16).replace('T', ' ')
  const ist = new Date(d.getTime() + 5.5 * 3600 * 1000)
    .toISOString()
    .slice(0, 16)
    .replace('T', ' ')
  return { utc: `${utc} UTC`, ist: `${ist} IST` }
}

export function relativeTime(iso) {
  if (!iso) return DASH
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  const seconds = (Date.now() - d.getTime()) / 1000
  if (Number.isNaN(seconds)) return DASH
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86400)} d ago`
}

export function tagClass(level) {
  return `tag tag-${String(level || 'low').toLowerCase()}`
}
