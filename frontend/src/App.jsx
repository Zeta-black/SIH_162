import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { HashRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api.js'
import { buildClassMap } from './lib/classes.js'
import { useApi } from './lib/useApi.js'
import { ErrorState, Loading } from './components/ui.jsx'
import {
  IconAlert,
  IconData,
  IconFlame,
  IconGauge,
  IconMap,
  IconMethod,
  IconModel,
  IconRefresh,
  IconReplay,
} from './components/icons.jsx'
import Operations from './pages/Operations.jsx'
import Incidents from './pages/Incidents.jsx'
import Explore from './pages/Explore.jsx'
import Model from './pages/Model.jsx'
import DataSources from './pages/DataSources.jsx'
import Method from './pages/Method.jsx'
import Replay from './pages/Replay.jsx'

/**
 * Area of interest, observation window and data source live at the shell, not
 * inside a page. Two reasons: the command bar is always on screen, and the
 * backend caches an analysis for 20 minutes — so sharing the query means
 * switching pages reads from cache instead of re-querying NASA.
 */
const QueryContext = createContext(null)
export const useQueryState = () => useContext(QueryContext)

const MetaContext = createContext(null)
export const useMeta = () => useContext(MetaContext)

export const REGIONS = [
  { id: 'india', label: 'India — national', bbox: '68.0,6.5,97.5,36.0' },
  { id: 'gujarat', label: 'Gujarat industrial belt', bbox: '68.5,20.5,74.0,24.5' },
  { id: 'central', label: 'Central India coal & power', bbox: '79.5,20.5,85.5,24.5' },
  { id: 'north', label: 'Punjab & Haryana cropland', bbox: '74.0,28.5,78.0,32.0' },
  { id: 'east', label: 'Odisha & Jharkhand', bbox: '83.5,19.5,87.5,24.0' },
  { id: 'south', label: 'Southern industry & forest', bbox: '75.5,10.5,84.0,18.5' },
  { id: 'world', label: 'Global (explicit high-volume query)', bbox: '-180,-90,180,90' },
]

const NAV = [
  { to: '/ops', label: 'Overview', Icon: IconGauge, title: 'Current operational picture' },
  { to: '/incidents', label: 'Alerts', Icon: IconAlert, title: 'Alert queue and response workflow' },
  { to: '/explore', label: 'Map', Icon: IconMap, title: 'India-focused geospatial workspace' },
  { to: '/replay', label: 'Replay', Icon: IconReplay, title: 'Replay a historical event through the pipeline' },
  { to: '/model', label: 'Model', Icon: IconModel, title: 'Model evidence and limitations' },
  { to: '/data', label: 'History', Icon: IconData, title: 'Historical source provenance' },
  { to: '/method', label: 'System', Icon: IconMethod, title: 'Processing chain, policy, and limits' },
]

function SourceChip({ status, error, loading }) {
  if (error) {
    return (
      <span className="chip chip-alarm" title={error.message}>
        <span className="led" />
        Link down
      </span>
    )
  }
  if (loading && !status) {
    return (
      <span className="chip chip-idle">
        <span className="spin" style={{ width: 9, height: 9, borderWidth: 1.5 }} />
        Acquiring
      </span>
    )
  }
  if (!status) return <span className="chip chip-idle">Standby</span>

  // A requested live query can complete with the upstream source unavailable.
  // Do not turn that degraded backend state into a misleading healthy-feed LED.
  const unavailable = status.firms_status === 'unavailable' || status.firms_status === 'not_configured'
  if (unavailable) {
    return (
      <span className="chip chip-alarm" title={status.firms_message}>
        <span className="led" />
        Degraded fallback
      </span>
    )
  }
  const live = status.mode === 'live'
  return (
    <span className={live ? 'chip chip-live' : 'chip chip-hist'} title={status.firms_message}>
      <span className={live ? 'led led-on' : 'led'} />
      {live ? 'Live NASA FIRMS' : 'Historical'}
    </span>
  )
}

/** Command bar: the controls that change what is on screen, always visible. */
function CommandBar() {
  const { regionId, setRegionId, days, setDays, mode, setMode, query, onRefresh, busy, window } =
    useQueryState()

  return (
    <div className="cmdbar">
      <div className="cmd-group">
        <span className="cmd-label">Area</span>
        <select
          className="sel"
          style={{ width: 208 }}
          value={regionId}
          onChange={(e) => setRegionId(e.target.value)}
          aria-label="Area of interest"
        >
          {REGIONS.map((r) => (
            <option key={r.id} value={r.id}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <div className="cmd-group">
        <span className="cmd-label">Window</span>
        <select
          className="sel"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          aria-label="Observation window"
        >
          {[1, 2, 3, 4, 5].map((d) => (
            <option key={d} value={d}>
              {d}d
            </option>
          ))}
        </select>
        {/* The real acquisition dates, not just the nominal span. */}
        <span className="m xs faint nw">{window.label}</span>
      </div>

      <div className="cmd-group">
        <span className="cmd-label">Source</span>
        <div className="seg">
          {[
            ['auto', 'Auto'],
            ['live', 'Live'],
            ['demo', 'Historical'],
          ].map(([value, label]) => (
            <button key={value} aria-pressed={mode === value} onClick={() => setMode(value)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="cmd-gap" />

      <div className="cmd-group" style={{ borderRight: 0 }}>
        <a className="btn" href={api.jsonUrl(query)} download title="Export canonical event evidence as JSON">
          JSON
        </a>
        <a className="btn" href={api.csvUrl(query)} download title="Export current view as CSV">
          CSV
        </a>
        <a
          className="btn"
          href={api.geojsonUrl(query)}
          target="_blank"
          rel="noreferrer"
          title="Export current view as GeoJSON"
        >
          GeoJSON
        </a>
        <button className="btn btn-go" onClick={onRefresh} disabled={busy}>
          {busy ? <span className="spin" style={{ borderTopColor: '#fff' }} /> : <IconRefresh />}
          {busy ? 'Working' : 'Refresh'}
        </button>
      </div>
    </div>
  )
}

/** Status strip: machine state, always on screen, never inferred. */
function StatusBar() {
  const { status, summary, model, latency, window } = useQueryState()

  const cells = [
    [
      'SRC',
      status
        ? status.firms_status === 'unavailable' || status.firms_status === 'not_configured'
          ? 'NASA FIRMS · degraded'
          : status.mode === 'live'
            ? 'NASA FIRMS · live'
            : 'FIRMS · frozen capture'
        : '—',
    ],
    ['PRODUCTS', status?.firms_products_used?.length ? status.firms_products_used.join(' ') : '—'],
    ['RECORDS', summary ? summary.total_events.toLocaleString('en-IN') : '—'],
    ['WINDOW', window.label],
    ['GEO', status ? `OSM ${status.osm_status}` : '—'],
    ['LANDCOVER', status?.land_cover_provider ?? '—'],
    ['MODEL', model?.loaded ? `RF v${model.model_version} · ${model.n_features}f` : 'not loaded'],
  ]

  return (
    <div className="statusbar">
      {cells.map(([k, v]) => (
        <div className="status-cell" key={k}>
          <span className="status-key">{k}</span>
          <span className="status-val">{v}</span>
        </div>
      ))}
      <div className="status-gap" />
      {latency != null && (
        <div className="status-cell">
          <span className="status-key">LAST QUERY</span>
          <span className="status-val">{latency.toFixed(1)}s</span>
        </div>
      )}
      <div className="status-cell" style={{ borderRight: 0 }}>
        <span className="status-key">UTC</span>
        <span className="status-val">{new Date().toISOString().slice(11, 16)}</span>
      </div>
    </div>
  )
}

function Shell({ children }) {
  const { status, statusError, statusLoading } = useQueryState()
  return (
    <div className="console">
      <header className="masthead">
        <div className="mark">
          <span className="mark-glyph">
            <IconFlame style={{ color: '#fff' }} />
          </span>
          <span className="mark-text">
            <span className="mark-name">FIRETRACE</span>
            <span className="mark-sub">Satellite Fire Intelligence &amp; Response</span>
          </span>
        </div>

        <nav className="nav">
          {NAV.map(({ to, label, Icon, title }) => (
            <NavLink
              key={to}
              to={to}
              title={title}
              className={({ isActive }) => (isActive ? 'active' : undefined)}
            >
              <Icon />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="masthead-gap" />
        <div className="masthead-stat">
          <SourceChip status={status} error={statusError} loading={statusLoading} />
        </div>
      </header>

      <CommandBar />
      {children}
      <StatusBar />
    </div>
  )
}

function Boot({ error, onRetry }) {
  return (
    <div style={{ height: '100%', display: 'grid', placeItems: 'center', background: 'var(--ground)' }}>
      <div style={{ width: 440, maxWidth: '90vw' }}>
        <div className="mod">
          <div className="mod-head">
            <span className="mod-title">FIRETRACE</span>
          </div>
          <div className="mod-body">
            {error ? (
              <ErrorState error={error} onRetry={onRetry} what="the analysis backend" />
            ) : (
              <Loading label="Connecting to the analysis backend…" />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [regionId, setRegionId] = useState('india')
  const [days, setDays] = useState(1)
  const [mode, setMode] = useState('auto')
  const [refreshToken, setRefreshToken] = useState(0)

  const region = useMemo(() => REGIONS.find((r) => r.id === regionId) ?? REGIONS[0], [regionId])

  const meta = useApi(() => api.meta(), [])
  const modelInfo = useApi(() => api.modelInfo(), [])
  const classMap = useMemo(() => buildClassMap(meta.data), [meta.data])

  // Pages report the analysis they actually rendered, so the masthead chip and
  // the status strip can never describe data that is not on screen.
  const [status, setStatus] = useState(null)
  const [summary, setSummary] = useState(null)
  const [statusError, setStatusError] = useState(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [latency, setLatency] = useState(null)

  const reportStatus = useCallback((next) => {
    setStatus(next?.status ?? null)
    setSummary(next?.summary ?? null)
    setStatusError(next?.error ?? null)
    setStatusLoading(Boolean(next?.loading))
    if (next?.latency != null) setLatency(next.latency)
  }, [])

  const onRefresh = useCallback(async () => {
    try {
      await api.refresh()
    } catch {
      // Cache clear is best effort; reload regardless.
    }
    setRefreshToken((t) => t + 1)
  }, [])

  const window = useMemo(() => {
    const range = summary?.date_range
    if (range?.from && range?.to) {
      return {
        label: range.from === range.to ? range.from : `${range.from}→${range.to}`,
        detail: `${days}-day request`,
      }
    }
    return { label: `last ${days}d`, detail: 'no detections' }
  }, [summary, days])

  const value = useMemo(
    () => ({
      region,
      regionId,
      setRegionId,
      days,
      setDays,
      mode,
      setMode,
      query: { bbox: region.bbox, days, mode },
      refreshToken,
      onRefresh,
      busy: statusLoading,
      status,
      summary,
      statusError,
      statusLoading,
      reportStatus,
      model: modelInfo.data,
      latency,
      window,
    }),
    [
      region, regionId, days, mode, refreshToken, onRefresh,
      status, summary, statusError, statusLoading, reportStatus,
      modelInfo.data, latency, window,
    ],
  )

  if (meta.loading || meta.error) return <Boot error={meta.error} onRetry={meta.reload} />

  return (
    <HashRouter>
      <MetaContext.Provider value={{ meta: meta.data, classMap }}>
        <QueryContext.Provider value={value}>
          <Shell>
            <Routes>
              <Route path="/" element={<Navigate to="/ops" replace />} />
              <Route path="/ops" element={<Operations />} />
              <Route path="/incidents" element={<Incidents />} />
              <Route path="/explore" element={<Explore />} />
              <Route path="/model" element={<Model />} />
              <Route path="/data" element={<DataSources />} />
              <Route path="/method" element={<Method />} />
              <Route path="/replay" element={<Replay />} />
              <Route path="*" element={<Navigate to="/ops" replace />} />
            </Routes>
          </Shell>
        </QueryContext.Provider>
      </MetaContext.Provider>
    </HashRouter>
  )
}
