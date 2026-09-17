import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useMeta, useQueryState } from '../App.jsx'
import { useApi } from '../lib/useApi.js'
import { useAnalysis } from '../lib/useAnalysis.js'
import { int, km, num, pct, utcAndIst } from '../lib/format.js'
import MapView from '../components/MapView.jsx'
import Inspector from '../components/Inspector.jsx'
import { ClassMark, ErrorState, Priority } from '../components/ui.jsx'

const DEFAULT_FILTERS = {
  classification: [],
  priority: [],
  min_confidence: 0,
  max_facility_km: '',
  persistent_only: false,
}

const COLS = [
  { id: 'priority', label: 'Pri', get: (e) => e.priority.score, r: true },
  { id: 'class', label: 'Likely source', get: (e) => e.classification.label },
  { id: 'confidence', label: 'RF score', get: (e) => e.classification.confidence, r: true },
  { id: 'time', label: 'Acquired IST', get: (e) => e.event.acquired_at },
  { id: 'frp', label: 'FRP MW', get: (e) => e.event.frp_mw ?? -1, r: true },
  {
    id: 'facility',
    label: 'Nearest facility',
    get: (e) => e.evidence.distance_to_nearest_facility_km ?? Number.MAX_SAFE_INTEGER,
  },
  { id: 'landcover', label: 'Land cover', get: (e) => e.evidence.land_cover.category },
  { id: 'days', label: 'Days', get: (e) => e.evidence.recurrence.distinct_days, r: true },
]

function DockSection({ title, action, children }) {
  return (
    <section className="dock-sec">
      <header className="dock-head">
        <span>{title}</span>
        {action}
      </header>
      <div className="dock-body">{children}</div>
    </section>
  )
}

export default function Explore() {
  const { query, reportStatus, refreshToken } = useQueryState()
  const { meta, classMap } = useMeta()

  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [selectedId, setSelectedId] = useState(null)
  const [showFacilities, setShowFacilities] = useState(true)
  const [showRing, setShowRing] = useState(true)
  const [basemap, setBasemap] = useState('muted')
  const [sort, setSort] = useState({ key: 'priority', dir: 'desc' })
  const [gridOpen, setGridOpen] = useState(true)

  const analysis = useAnalysis({ query, reportStatus, limit: 900, refreshToken })
  const facilities = useApi(
    ({ signal } = {}) => api.facilities({ ...query, limit: 900 }, { signal }),
    [query.bbox, query.days, query.mode, refreshToken],
  )

  const all = useMemo(() => analysis.data?.events ?? [], [analysis.data])
  const summary = analysis.data?.summary
  const status = analysis.data?.status

  // Filtering is client-side so toggling a class is instant and costs no round
  // trip; only area, window and source re-query the external sources.
  const events = useMemo(
    () =>
      all.filter((it) => {
        if (
          filters.classification.length &&
          !filters.classification.includes(it.classification.label)
        )
          return false
        if (filters.priority.length && !filters.priority.includes(it.priority.level)) return false
        if (it.classification.confidence < filters.min_confidence) return false
        if (filters.max_facility_km !== '') {
          const d = it.evidence.distance_to_nearest_facility_km
          if (d === null || d > Number(filters.max_facility_km)) return false
        }
        if (filters.persistent_only && !it.evidence.recurrence.is_persistent) return false
        return true
      }),
    [all, filters],
  )

  const sorted = useMemo(() => {
    const col = COLS.find((c) => c.id === sort.key) ?? COLS[0]
    return [...events].sort((a, b) => {
      const av = col.get(a)
      const bv = col.get(b)
      if (av === bv) return 0
      return (av > bv ? 1 : -1) * (sort.dir === 'asc' ? 1 : -1)
    })
  }, [events, sort])

  // The list response explains only the top few; the inspector fetches the
  // full record for whichever detection was actually opened.
  const [detail, setDetail] = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    const local = all.find((e) => e.event.event_id === selectedId)
    if (!local) return
    setDetail(local)
    if (local.factors?.length) return

    let cancelled = false
    setLoadingDetail(true)
    api
      .hotspot(selectedId, query)
      .then((full) => {
        if (!cancelled) setDetail(full)
      })
      .catch(() => {
        /* keep the unexplained record rather than blanking the panel */
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, all, query])

  const setFilter = (patch) => setFilters((f) => ({ ...f, ...patch }))
  const toggle = (key, value) =>
    setFilter({
      [key]: filters[key].includes(value)
        ? filters[key].filter((v) => v !== value)
        : [...filters[key], value],
    })
  const toggleSort = (key) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))

  const counts = summary?.by_class ?? {}
  const active =
    filters.classification.length ||
    filters.priority.length ||
    filters.min_confidence > 0 ||
    filters.max_facility_km !== '' ||
    filters.persistent_only

  return (
    <div className="workspace">
      {/* ── layers and filters ───────────────────────────────────────── */}
      <aside className="dock">
        <DockSection
          title="Classification"
          action={
            active ? (
              <button className="btn btn-xs" onClick={() => setFilters(DEFAULT_FILTERS)}>
                Reset
              </button>
            ) : null
          }
        >
          {(meta?.classes ?? []).map((c) => (
            <label className="chk" key={c.id}>
              <input
                type="checkbox"
                checked={filters.classification.includes(c.id)}
                onChange={() => toggle('classification', c.id)}
              />
              <span className="chk-body">
                <span className="code" style={{ color: c.color }}>
                  {c.code}
                </span>
                <span className="trunc">{c.label}</span>
              </span>
              <span className="chk-n">{int(counts[c.id] ?? 0)}</span>
            </label>
          ))}
        </DockSection>

        <DockSection title="Priority">
          {['HIGH', 'MEDIUM', 'LOW'].map((p) => (
            <label className="chk" key={p}>
              <input
                type="checkbox"
                checked={filters.priority.includes(p)}
                onChange={() => toggle('priority', p)}
              />
              <span className="chk-body">
                <Priority level={p} />
              </span>
              <span className="chk-n">{int(summary?.by_priority?.[p] ?? 0)}</span>
            </label>
          ))}
        </DockSection>

        <DockSection title="Evidence thresholds">
          <label className="cmd-label" htmlFor="conf" style={{ display: 'block', marginBottom: 3 }}>
            Min RF vote score — {pct(filters.min_confidence)}
          </label>
          <input
            id="conf"
            type="range"
            min="0"
            max="0.95"
            step="0.05"
            value={filters.min_confidence}
            onChange={(e) => setFilter({ min_confidence: Number(e.target.value) })}
          />

          <label
            className="cmd-label"
            htmlFor="fac"
            style={{ display: 'block', margin: '8px 0 3px' }}
          >
            Proximity to industry
          </label>
          <select
            id="fac"
            className="sel"
            style={{ width: '100%' }}
            value={filters.max_facility_km}
            onChange={(e) => setFilter({ max_facility_km: e.target.value })}
          >
            <option value="">Any distance</option>
            <option value="0.5">≤ 0.5 km — on site</option>
            <option value="1">≤ 1 km</option>
            <option value="3">≤ 3 km</option>
            <option value="5">≤ 5 km</option>
            <option value="10">≤ 10 km</option>
          </select>

          <label className="chk" style={{ marginTop: 6 }}>
            <input
              type="checkbox"
              checked={filters.persistent_only}
              onChange={(e) => setFilter({ persistent_only: e.target.checked })}
            />
            <span className="chk-body">Persistent sources only</span>
          </label>
        </DockSection>

        <DockSection title="Layers">
          <label className="chk">
            <input
              type="checkbox"
              checked={showFacilities}
              onChange={(e) => setShowFacilities(e.target.checked)}
            />
            <span className="chk-body">
              <span className="facpin" style={{ width: 9, height: 9 }} />
              Industrial facilities
            </span>
            <span className="chk-n">{int(facilities.data?.count ?? 0)}</span>
          </label>
          <label className="chk">
            <input
              type="checkbox"
              checked={showRing}
              onChange={(e) => setShowRing(e.target.checked)}
            />
            <span className="chk-body">Recurrence radius</span>
          </label>

          <div className="cmd-label" style={{ margin: '9px 0 4px' }}>
            Basemap
          </div>
          <div className="seg">
            {[
              ['muted', 'Muted'],
              ['standard', 'Std'],
              ['terrain', 'Terrain'],
            ].map(([v, l]) => (
              <button key={v} aria-pressed={basemap === v} onClick={() => setBasemap(v)}>
                {l}
              </button>
            ))}
          </div>
        </DockSection>
      </aside>

      {/* ── map stage ────────────────────────────────────────────────── */}
      <main className="stage">
        {analysis.error ? (
          <ErrorState error={analysis.error} onRetry={analysis.reload} what="the map data" />
        ) : (
          <>
            <MapView
              events={events}
              facilities={showFacilities ? (facilities.data?.facilities ?? []) : []}
              selectedId={selectedId}
              onSelect={setSelectedId}
              classMap={classMap}
              loading={analysis.loading}
              bboxKey={`${query.bbox}|${query.mode}`}
              showFacilities={showFacilities}
              showRecurrenceRing={showRing}
              recurrenceRadiusKm={meta?.feature_config?.recurrence_radius_km ?? 1}
              basemap={basemap}
              snapshot={status?.mode === 'snapshot'}
              sourceStatus={status}
            />

            <div
              style={{
                height: gridOpen ? 214 : 26,
                flexShrink: 0,
                borderTop: '1px solid var(--rule-strong)',
                background: 'var(--panel)',
                display: 'flex',
                flexDirection: 'column',
                minHeight: 0,
              }}
            >
              <div className="dock-head" style={{ position: 'static' }}>
                <span>
                  Detections — {int(events.length)}
                  {events.length !== all.length && ` of ${int(all.length)}`}
                </span>
                <button className="btn btn-xs" onClick={() => setGridOpen((o) => !o)}>
                  {gridOpen ? 'Collapse' : 'Expand'}
                </button>
              </div>

              {gridOpen && (
                <div className="gridwrap" style={{ flex: 1, minHeight: 0 }}>
                  <table className="grid">
                    <thead>
                      <tr>
                        {COLS.map((c) => (
                          <th
                            key={c.id}
                            className={`srt${c.r ? ' r' : ''}`}
                            onClick={() => toggleSort(c.id)}
                          >
                            {c.label}
                            {sort.key === c.id && (sort.dir === 'desc' ? ' ↓' : ' ↑')}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sorted.length === 0 && (
                        <tr>
                          <td
                            colSpan={COLS.length}
                            className="dim"
                            style={{ height: 54, textAlign: 'center' }}
                          >
                            {analysis.loading
                              ? 'Loading detections…'
                              : all.length === 0
                                ? 'No detections returned for this area and window.'
                                : 'No detections match the current filters.'}
                          </td>
                        </tr>
                      )}
                      {sorted.map((it) => {
                        const nf = it.evidence.nearest_facility
                        return (
                          <tr
                            key={it.event.event_id}
                            className={`hit${it.event.event_id === selectedId ? ' sel' : ''}`}
                            onClick={() => setSelectedId(it.event.event_id)}
                          >
                            <td className="r">
                              <Priority level={it.priority.level} score={it.priority.score} />
                            </td>
                            <td>
                              <ClassMark cls={classMap[it.classification.label]} />
                            </td>
                            <td className="num r">{pct(it.classification.confidence)}</td>
                            <td className="num dim">
                              {utcAndIst(it.event.acquired_at).ist.replace(' IST', '')}
                            </td>
                            <td className="num r">
                              {it.event.frp_mw === null ? (
                                <span className="na">n/r</span>
                              ) : (
                                num(it.event.frp_mw)
                              )}
                            </td>
                            <td className="dim">
                              {nf ? (
                                <>
                                  <span className="num">
                                    {km(it.evidence.distance_to_nearest_facility_km)}
                                  </span>{' '}
                                  {nf.name || nf.category_label}
                                </>
                              ) : (
                                <span className="na">none in radius</span>
                              )}
                            </td>
                            <td className="dim">
                              {it.evidence.land_cover.category === 'unknown' ? (
                                <span className="na">unmapped</span>
                              ) : (
                                it.evidence.land_cover.label
                              )}
                            </td>
                            <td className="num r dim">
                              {it.evidence.recurrence.history_available
                                ? it.evidence.recurrence.distinct_days
                                : '—'}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </main>

      <Inspector item={detail} classMap={classMap} loadingDetail={loadingDetail} />
    </div>
  )
}
