import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from './api.js'
import CalmMap from './components/map/CalmMap.jsx'
import {
  AttentionList,
  BrandCard,
  EvidenceDrawer,
  FallbackBanner,
  FilterChips,
  SearchBar,
  SiteCard,
} from './components/map/Panels.jsx'
import { IconLayers } from './components/map/mapicons.jsx'
import './map.css'

/**
 * FIRETRACE main screen.
 *
 * One map, four floating panels, nothing else. The seven analytics pages the
 * project already had are still there and still work — they moved behind the
 * single "Analytics" link in the corner, because they are reference material
 * for an analyst, not the first thing a safety officer or an evaluator should
 * have to parse.
 *
 * All data for this screen comes from one request (`/api/map`), so the status
 * summary, the markers, the cards and the provenance chip can never describe
 * different snapshots of the world.
 */

const INDIA_BBOX = '68.0,6.5,97.5,36.0'
const POLL_MS = 5 * 60 * 1000

/**
 * Read a query parameter from either side of the hash.
 *
 * Under a HashRouter people reliably type `#/?demo=1`, which never reaches
 * `window.location.search`, while a pasted link is usually `?demo=1#/`. Both
 * have to work or the offline switch silently does nothing.
 */
function readParam(key) {
  if (typeof window === 'undefined') return null
  const hash = window.location.hash
  const inHash = hash.includes('?') ? hash.slice(hash.indexOf('?')) : ''
  return new URLSearchParams(window.location.search).get(key) ?? new URLSearchParams(inHash).get(key)
}

export default function MapApp() {
  const [mode, setMode] = useState(() => {
    const get = readParam
    if (get('demo') === '1') return 'demo'
    if (get('live') === '1') return 'live'
    return 'auto'
  })

  /* ?site=FE-2026-43C5 opens that exact site.
   *
   * Added because a demo script that says "click the first row" is a script
   * that breaks the moment the ranking changes — and the ranking changed the
   * day the abnormality fix landed. A link is also the natural way an operator
   * hands a colleague a specific event. */
  const [deepLinkSite] = useState(() => readParam('site'))
  const deepLinkDone = useRef(false)
  const [days, setDays] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)

  const [selectedId, setSelectedId] = useState(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [filters, setFilters] = useState([])
  const [reviewed, setReviewed] = useState(() => new Set())
  const [flyTo, setFlyTo] = useState(null)

  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)

  const reqRef = useRef(0)

  // ------------------------------------------------------------ load data
  const load = useCallback(
    async (opts = {}) => {
      const id = ++reqRef.current
      if (opts.quiet) setReloading(true)
      else setLoading(true)
      try {
        const next = await api.map({ bbox: INDIA_BBOX, days, mode })
        if (id !== reqRef.current) return // a newer request already won
        setData(next)
        setError(null)
      } catch (e) {
        if (id !== reqRef.current) return
        setError(e)
      } finally {
        if (id === reqRef.current) {
          setLoading(false)
          setReloading(false)
        }
      }
    },
    [days, mode],
  )

  useEffect(() => {
    load()
  }, [load])

  // Refresh quietly in the background so a long demo does not go stale. Never
  // blocks the UI and never clears what is already on screen.
  useEffect(() => {
    const t = setInterval(() => load({ quiet: true }), POLL_MS)
    return () => clearInterval(t)
  }, [load])

  // --------------------------------------------------------------- search
  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setResults(null)
      return
    }
    let cancelled = false
    setSearching(true)
    const t = setTimeout(async () => {
      try {
        const r = await api.mapSearch({ q, bbox: INDIA_BBOX, days, mode })
        if (!cancelled) setResults(r.results)
      } catch {
        if (!cancelled) setResults([])
      } finally {
        if (!cancelled) setSearching(false)
      }
    }, 220)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [query, days, mode])

  // ---------------------------------------------------------------- derive
  // Memoised because every hook below depends on it; a fresh [] each render
  // would re-cluster and re-draw every marker on every keystroke.
  const sites = useMemo(() => data?.sites ?? [], [data])

  const visible = useMemo(
    () => (filters.length ? sites.filter((s) => filters.includes(s.status)) : sites),
    [sites, filters],
  )

  // The queue is whatever the user is currently looking at, most urgent first.
  // /api/map already returns sites in triage order.
  const queue = useMemo(
    () => visible.filter((s) => s.status === 'needs_attention' || s.status === 'not_sure'),
    [visible],
  )

  const selected = useMemo(
    () => sites.find((s) => s.id === selectedId) ?? null,
    [sites, selectedId],
  )

  // Only the single most urgent site pulses, and only when it is a real one.
  const pulseId = useMemo(() => {
    const first = visible.find((s) => s.status === 'needs_attention')
    return first?.id ?? null
  }, [visible])

  const pick = useCallback(
    (id) => {
      setSelectedId(id)
      const site = sites.find((s) => s.id === id)
      if (site) setFlyTo({ lat: site.lat, lon: site.lon, zoom: 11, k: Date.now() })
    },
    [sites],
  )

  // Open the deep-linked site as soon as the data it refers to exists.
  useEffect(() => {
    if (deepLinkDone.current || !deepLinkSite || !sites.length) return
    const match = sites.find((s) => s.id === deepLinkSite)
    if (!match) return
    deepLinkDone.current = true
    setSelectedId(match.id)
    setFlyTo({ lat: match.lat, lon: match.lon, zoom: 12, k: Date.now() })
  }, [deepLinkSite, sites])

  const onPickResult = useCallback(
    (r) => {
      setQuery('')
      setResults(null)
      if (r.kind === 'site') {
        pick(r.id)
      } else {
        setSelectedId(null)
        setFlyTo({ lat: r.lat, lon: r.lon, zoom: 12, k: Date.now() })
      }
    },
    [pick],
  )

  const toggleFilter = useCallback((key) => {
    setFilters((f) => (f.includes(key) ? f.filter((x) => x !== key) : [...f, key]))
  }, [])

  // Escape closes the card. The drawer handles its own Escape.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && !drawerOpen && selectedId) setSelectedId(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen, selectedId])

  // ----------------------------------------------------------------- error
  // A backend that is not up yet is the single most likely failure on a demo
  // laptop, so it gets a real explanation rather than a dead map.
  if (error && !data) {
    return (
      <div className="mapapp">
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'grid',
            placeItems: 'center',
            padding: 24,
          }}
        >
          <div className="m-panel" style={{ position: 'static', padding: 24, maxWidth: 420 }}>
            <div className="m-brand">
              <span className="m-brand-name">FIRETRACE</span>
            </div>
            <p style={{ fontSize: 14, lineHeight: 1.5, color: 'var(--m-ink-2)' }}>
              {error.message}
            </p>
            <button className="m-btn m-btn-primary" onClick={() => load()} style={{ width: '100%' }}>
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="mapapp">
      <CalmMap
        sites={visible}
        selectedId={selectedId}
        onSelect={pick}
        flyTo={flyTo}
        pulseId={pulseId}
      />

      <BrandCard
        counts={data?.counts}
        provenance={data?.provenance}
        observedTo={data?.window?.observed_to}
        loading={loading}
        mode={mode}
        onMode={setMode}
        busy={reloading}
      />

      <div className="m-searchwrap">
        <SearchBar
          value={query}
          onChange={setQuery}
          results={results}
          onPick={onPickResult}
          busy={searching}
          loading={loading}
        />
        <FilterChips
          active={filters}
          onToggle={toggleFilter}
          windowDays={days}
          onWindow={setDays}
          counts={data?.counts}
        />
      </div>

      <AttentionList sites={queue} onPick={pick} selectedId={selectedId} />

      {selected && (
        <SiteCard
          site={selected}
          onClose={() => setSelectedId(null)}
          onEvidence={() => setDrawerOpen(true)}
          onReview={() => setReviewed((r) => new Set(r).add(selected.id))}
          reviewed={reviewed.has(selected.id)}
        />
      )}

      {drawerOpen && selected && (
        <EvidenceDrawer
          site={selected}
          provenance={data?.provenance}
          model={data?.model}
          disclaimer={data?.disclaimer}
          onClose={() => setDrawerOpen(false)}
        />
      )}

      <FallbackBanner
        provenance={data?.provenance}
        onRetry={() => load({ quiet: true })}
        busy={reloading}
      />

      <div className="m-footlink">
        <Link className="m-ghost" to="/analytics/ops">
          <IconLayers width={14} height={14} />
          Analytics
        </Link>
      </div>

      {/* Announced to screen readers when the picture changes, so the summary
          is not only available visually. */}
      <div className="m-sr" role="status" aria-live="polite">
        {data
          ? `${data.counts.needs_attention} need attention, ${data.counts.watch} watch, ${data.counts.normal} normal, ${data.counts.not_sure} not sure. Data state: ${data.provenance.label}.`
          : 'Loading detections'}
      </div>
    </div>
  )
}
