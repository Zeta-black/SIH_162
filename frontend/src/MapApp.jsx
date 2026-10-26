import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from './api.js'
import CalmMap, { SATELLITE_AVAILABLE } from './components/map/CalmMap.jsx'
import LiveControl, { PastBanner } from './components/map/LiveControl.jsx'
import SiteCard from './components/map/SiteCard.jsx'
import Timeline from './components/map/Timeline.jsx'
import { EvidenceDrawer, FilterChips, SearchBar } from './components/map/Panels.jsx'
import {
  NewItemsPill,
  NotificationBell,
  NotificationToast,
  useBrowserNotifications,
  useNotificationFeed,
} from './components/map/Notifications.jsx'
import {
  AboutButton,
  AboutSheet,
  CommandPalette,
  LayersControl,
  MapTypeControl,
} from './components/map/Controls.jsx'
import { IconLayers } from './components/map/mapicons.jsx'
import '@fontsource-variable/inter'
import './tokens.css'
import './app.css'
import './card.css'

/**
 * FIRETRACE operations screen.
 *
 * One map. Four floating panels plus the map controls. The seven analyst pages
 * the project already had still work and still exist — they sit behind one
 * small Analytics link, because they are reference material rather than the
 * first thing a safety officer should have to parse.
 *
 * All map data comes from one request (`/api/map`), so the summary counts, the
 * markers, the card and the freshness line can never describe different
 * snapshots of the world.
 */

const INDIA_BBOX = '68.0,6.5,97.5,36.0'
const MAP_POLL_MS = 5 * 60 * 1000
const LAYER_STORAGE_KEY = 'firetrace.layers'

function readParam(key) {
  if (typeof window === 'undefined') return null
  const hash = window.location.hash
  const inHash = hash.includes('?') ? hash.slice(hash.indexOf('?')) : ''
  return (
    new URLSearchParams(window.location.search).get(key) ??
    new URLSearchParams(inHash).get(key)
  )
}

function loadLayers() {
  const fallback = {
    detections: true,
    persistent: true,
    facilities: false,
    industrial: false,
    landcover: false,
  }
  try {
    const stored = JSON.parse(localStorage.getItem(LAYER_STORAGE_KEY) ?? 'null')
    return stored ? { ...fallback, ...stored } : fallback
  } catch {
    return fallback
  }
}

export default function MapApp() {
  // `?demo=1` is kept as an alias for Past data so the Pass 1 deep links in the
  // demo pack and the checklist keep working.
  const [rangeId, setRangeId] = useState(() =>
    readParam('range') ?? (readParam('demo') === '1' ? 'latest-archive' : null),
  )
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const [selectedId, setSelectedId] = useState(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [filters, setFilters] = useState([])
  const [reviewed, setReviewed] = useState(() => new Set())
  const [flyTo, setFlyTo] = useState(null)

  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)

  const [mapType, setMapType] = useState('map')
  const [layers, setLayers] = useState(loadLayers)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [dayIndex, setDayIndex] = useState(0)
  const [newIds, setNewIds] = useState(() => new Set())
  const [pendingNew, setPendingNew] = useState(0)

  const reqRef = useRef(0)
  const interactingRef = useRef(false)
  const knownSiteIds = useRef(new Set())
  const [deepLinkSite] = useState(() => readParam('site'))
  const deepLinkDone = useRef(false)

  const isPast = data?.provenance?.surface === 'past'

  // ----------------------------------------------------------- load map
  const load = useCallback(async () => {
    const id = ++reqRef.current
    setLoading(true)
    try {
      const next = await api.map({
        bbox: INDIA_BBOX,
        days: 1,
        mode: rangeId ? 'demo' : 'auto',
        range: rangeId && rangeId !== 'latest-archive' ? rangeId : undefined,
      })
      if (id !== reqRef.current) return

      // Mark genuinely new sites so they can ring once, and count them for the
      // pill if the user is panned elsewhere.
      const incoming = new Set((next.sites ?? []).map((s) => s.id))
      if (knownSiteIds.current.size > 0) {
        const fresh = [...incoming].filter((sid) => !knownSiteIds.current.has(sid))
        if (fresh.length) {
          setNewIds(new Set(fresh))
          if (interactingRef.current) setPendingNew(fresh.length)
          setTimeout(() => setNewIds(new Set()), 4000)
        }
      }
      knownSiteIds.current = incoming

      setData(next)
      setError(null)
    } catch (e) {
      if (id === reqRef.current) setError(e)
    } finally {
      if (id === reqRef.current) setLoading(false)
    }
  }, [rangeId])

  useEffect(() => {
    load()
  }, [load])

  // Refresh quietly so a long demo does not go stale. Never blocks the UI and
  // never clears what is on screen.
  useEffect(() => {
    if (isPast) return undefined
    const timer = setInterval(load, MAP_POLL_MS)
    return () => clearInterval(timer)
  }, [load, isPast])

  // `?demo=1` with no explicit range resolves to the newest archive period once
  // the ranges are known, rather than hard-coding one.
  useEffect(() => {
    if (rangeId !== 'latest-archive') return
    const archive = (data?.ranges ?? []).find((r) => r.kind === 'archive')
    if (archive) setRangeId(archive.id)
  }, [rangeId, data?.ranges])

  // --------------------------------------------------------- notifications
  const notifications = useNotificationFeed(api, { isPast })
  useBrowserNotifications(notifications.items, !isPast)

  // ---------------------------------------------------------------- search
  const runSearch = useCallback(
    async (text) => {
      const q = text.trim()
      if (q.length < 2) {
        setResults(null)
        return
      }
      setSearching(true)
      try {
        const r = await api.mapSearch({
          q,
          bbox: INDIA_BBOX,
          days: 1,
          mode: rangeId ? 'demo' : 'auto',
        })
        setResults(r.results)
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    },
    [rangeId],
  )

  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setResults(null)
      return undefined
    }
    const timer = setTimeout(() => runSearch(q), 220)
    return () => clearTimeout(timer)
  }, [query, runSearch])

  // ---------------------------------------------------------------- derive
  // Memoised, or the `?? []` fallback allocates a new array on every render and
  // invalidates every downstream memo — which for a few hundred markers means
  // redrawing the whole map on each keystroke.
  const sites = useMemo(() => data?.sites ?? [], [data?.sites])

  const activeRange = useMemo(
    () => (data?.ranges ?? []).find((r) => r.id === rangeId) ?? null,
    [data?.ranges, rangeId],
  )

  // In Past mode the scrubber limits what is drawn to the days played so far.
  const dayFiltered = useMemo(() => {
    if (!isPast || !activeRange) return sites
    const days = []
    const cursor = new Date(`${activeRange.from}T00:00:00Z`)
    const end = new Date(`${activeRange.to}T00:00:00Z`)
    while (cursor <= end) {
      days.push(cursor.toISOString().slice(0, 10))
      cursor.setUTCDate(cursor.getUTCDate() + 1)
    }
    const cutoff = days[Math.min(dayIndex, days.length - 1)]
    if (!cutoff) return sites
    return sites.filter((s) => (s.observed_at ?? '').slice(0, 10) <= cutoff)
  }, [sites, isPast, activeRange, dayIndex])

  const visible = useMemo(
    () => (filters.length ? dayFiltered.filter((s) => filters.includes(s.status)) : dayFiltered),
    [dayFiltered, filters],
  )

  const detectionsByDay = useMemo(() => {
    const out = {}
    for (const s of sites) {
      const day = (s.observed_at ?? '').slice(0, 10)
      if (day) out[day] = (out[day] ?? 0) + (s.detection_count ?? 1)
    }
    return out
  }, [sites])

  const queue = useMemo(
    () => visible.filter((s) => s.status === 'needs_attention' || s.status === 'not_sure'),
    [visible],
  )

  const selected = useMemo(
    () => sites.find((s) => s.id === selectedId) ?? null,
    [sites, selectedId],
  )

  const pulseId = useMemo(
    () => visible.find((s) => s.status === 'needs_attention')?.id ?? null,
    [visible],
  )

  const counts = useMemo(() => {
    if (!isPast) return data?.counts
    // In Past mode the counts must describe what the scrubber is showing, not
    // the whole range, or the summary contradicts the map.
    const tally = { needs_attention: 0, watch: 0, normal: 0, not_sure: 0 }
    for (const s of dayFiltered) tally[s.status] += 1
    return tally
  }, [isPast, data?.counts, dayFiltered])

  // ---------------------------------------------------------------- actions
  const pick = useCallback(
    (id) => {
      setSelectedId(id)
      setPendingNew(0)
      const site = sites.find((s) => s.id === id)
      if (site) setFlyTo({ lat: site.lat, lon: site.lon, zoom: 11, k: Date.now() })
    },
    [sites],
  )

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
      if (r.kind === 'site') pick(r.id)
      else {
        setSelectedId(null)
        setFlyTo({ lat: r.lat, lon: r.lon, zoom: 12, k: Date.now() })
      }
    },
    [pick],
  )

  const toggleLayer = useCallback((key) => {
    setLayers((current) => {
      const next = { ...current, [key]: !current[key] }
      try {
        localStorage.setItem(LAYER_STORAGE_KEY, JSON.stringify(next))
      } catch {
        // A browser with storage disabled still gets a working session.
      }
      return next
    })
  }, [])

  const copyLink = useCallback(async () => {
    if (!selected) return false
    const url = `${window.location.origin}${window.location.pathname}?site=${selected.id}${
      rangeId ? `&range=${rangeId}` : ''
    }`
    try {
      await navigator.clipboard.writeText(url)
      return true
    } catch {
      return false
    }
  }, [selected, rangeId])

  const goLive = useCallback(() => {
    setRangeId(null)
    setDayIndex(0)
  }, [])

  const selectRange = useCallback((range) => {
    setRangeId(range.id)
    setSelectedId(null)
  }, [])

  // ------------------------------------------------------- command palette
  const commands = useMemo(
    () => [
      { id: 'cmd:live', label: 'Switch to Live', group: 'Data', run: goLive },
      ...(data?.ranges ?? []).slice(0, 4).map((range) => ({
        id: `cmd:range:${range.id}`,
        label: `Past data — ${range.label}`,
        hint: `${range.detections.toLocaleString('en-IN')} detections`,
        group: 'Data',
        run: () => selectRange(range),
      })),
      {
        id: 'cmd:attention',
        label: 'Show only Needs attention',
        group: 'View',
        run: () => setFilters(['needs_attention']),
      },
      { id: 'cmd:clear', label: 'Clear filters', group: 'View', run: () => setFilters([]) },
      {
        id: 'cmd:satellite',
        label: mapType === 'satellite' ? 'Switch to map view' : 'Switch to satellite view',
        group: 'View',
        run: () => setMapType(mapType === 'satellite' ? 'map' : 'satellite'),
      },
      ...['detections', 'persistent', 'facilities'].map((key) => ({
        id: `cmd:layer:${key}`,
        label: `Toggle layer — ${key}`,
        group: 'Layers',
        run: () => toggleLayer(key),
      })),
      { id: 'cmd:about', label: 'About this data', group: 'Help', run: () => setAboutOpen(true) },
    ],
    [data?.ranges, goLive, selectRange, mapType, toggleLayer],
  )

  useEffect(() => {
    const onKey = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      } else if (event.key === 'Escape' && !drawerOpen && !paletteOpen && selectedId) {
        setSelectedId(null)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen, paletteOpen, selectedId])

  const about = useMemo(
    () => ({
      facilities: data?.about?.facilities,
      detections: data?.counts?.detections,
      date_range: data?.about?.date_range,
      regions: data?.about?.regions,
      model_version: data?.model?.model_version,
      n_features: data?.model?.n_features,
      proxy_checks: data?.about?.proxy_checks,
    }),
    [data],
  )

  // ----------------------------------------------------------------- error
  if (error && !data) {
    return (
      <div className="fc-app">
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', padding: 24 }}>
          <div className="fc-panel" style={{ position: 'static', padding: 24, maxWidth: 420 }}>
            <div className="fc-live-head">
              <span className="fc-wordmark">FIRETRACE</span>
            </div>
            <p style={{ fontSize: 14, lineHeight: 1.55, color: 'var(--ink-2)' }}>{error.message}</p>
            <button type="button" className="fc-btn fc-btn-primary" onClick={load} style={{ width: '100%' }}>
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fc-app">
      <CalmMap
        sites={visible}
        selectedId={selectedId}
        onSelect={pick}
        flyTo={flyTo}
        pulseId={pulseId}
        newIds={newIds}
        mapType={mapType}
        layers={layers}
        onUserInteract={() => {
          interactingRef.current = true
        }}
      />

      <PastBanner provenance={data?.provenance} onExit={goLive} />

      <LiveControl
        provenance={data?.provenance}
        ranges={data?.ranges}
        activeRange={activeRange}
        onSelectLive={goLive}
        onSelectRange={selectRange}
        loading={loading}
        counts={counts}
      />

      <div className="fc-searchwrap">
        <SearchBar
          value={query}
          onChange={setQuery}
          results={results}
          onPick={onPickResult}
          busy={searching}
          loading={loading}
        />
        <FilterChips active={filters} onToggle={(key) =>
          setFilters((f) => (f.includes(key) ? f.filter((x) => x !== key) : [...f, key]))
        } counts={counts} />
      </div>

      <div className="fc-topright">
        <AboutButton onClick={() => setAboutOpen(true)} />
        <NotificationBell
          items={notifications.items}
          counts={notifications.counts}
          preview={data?.notifications?.preview}
          isPast={isPast}
          onOpenSite={pick}
          onAction={async (id, action) => {
            await api.notificationAction(id, { action })
            notifications.refresh()
          }}
          onTest={async () => {
            const result = await api.notificationTest()
            notifications.refresh()
            return result
          }}
          webhookConfigured={notifications.webhookConfigured}
          policy={notifications.policy}
        />
      </div>

      <NewItemsPill
        count={pendingNew}
        onClick={() => {
          setPendingNew(0)
          interactingRef.current = false
          if (queue[0]) pick(queue[0].id)
        }}
      />

      {queue.length > 0 && (
        <div className="fc-panel fc-queue">
          <div className="fc-queue-head">Needs attention first</div>
          {queue.slice(0, 5).map((s) => (
            <button
              key={s.id}
              type="button"
              className="fc-queue-row"
              onClick={() => pick(s.id)}
              aria-current={s.id === selectedId ? 'true' : undefined}
            >
              <span
                className="fc-swatch"
                style={{
                  background:
                    s.status === 'needs_attention' ? 'var(--s-attn)' : 'var(--s-unsure)',
                }}
              />
              <span className="fc-queue-name">{s.title}</span>
            </button>
          ))}
        </div>
      )}

      <div className="fc-mapctl">
        <MapTypeControl
          mapType={mapType}
          onChange={setMapType}
          satelliteAvailable={SATELLITE_AVAILABLE}
        />
        <LayersControl
          layers={layers}
          onToggle={toggleLayer}
          onDownload={() => window.open(api.gpkgUrl({ mode: rangeId ? 'demo' : 'auto' }), '_blank')}
          layerAvailability={data?.layer_availability}
        />
      </div>

      {isPast && activeRange && (
        <Timeline
          range={activeRange}
          dayIndex={dayIndex}
          onDayIndex={setDayIndex}
          detectionsByDay={detectionsByDay}
        />
      )}

      {selected && (
        <SiteCard
          site={selected}
          onClose={() => setSelectedId(null)}
          onEvidence={() => setDrawerOpen(true)}
          onReview={() => setReviewed((r) => new Set(r).add(selected.id))}
          reviewed={reviewed.has(selected.id)}
          onCopyLink={copyLink}
          isPast={isPast}
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

      <NotificationToast
        item={isPast ? null : notifications.toast}
        onOpen={pick}
        onDismiss={notifications.dismissToast}
      />

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
        searchResults={results}
        onSearch={runSearch}
        onRun={(payload) => {
          if (payload.kind === 'site') onPickResult(payload.hit)
        }}
      />

      <AboutSheet open={aboutOpen} onClose={() => setAboutOpen(false)} about={about} />

      <div className="fc-footlink">
        <Link className="fc-ghost" to="/analytics/ops">
          <IconLayers width={14} height={14} />
          Analytics
        </Link>
      </div>

      <div className="fc-sr" role="status" aria-live="polite">
        {data
          ? `${counts?.needs_attention ?? 0} need attention, ${counts?.watch ?? 0} watch, ${counts?.normal ?? 0} normal, ${counts?.not_sure ?? 0} not sure. ${data.provenance.surface === 'past' ? 'Showing past data.' : 'Live feed.'}`
          : 'Loading detections'}
      </div>
    </div>
  )
}
