import { useNavigate } from 'react-router-dom'
import { useMeta, useQueryState } from '../App.jsx'
import { useAnalysis } from '../lib/useAnalysis.js'
import { int, km, num, pct, utcAndIst } from '../lib/format.js'
import {
  Bar,
  ClassMark,
  ErrorState,
  Loading,
  Metric,
  Module,
  Note,
  PipeNode,
  Priority,
  Provenance,
} from '../components/ui.jsx'
import { IconAlert, IconGauge, IconMethod, IconModel } from '../components/icons.jsx'

/**
 * The operational picture: what is burning, what needs attention first, and on
 * what evidence. Built as a worklist, not as an article — an operator scans it.
 */
export default function Operations() {
  const { query, region, reportStatus, refreshToken, window } = useQueryState()
  const { classMap } = useMeta()
  const navigate = useNavigate()

  const { data, error, loading, reload, fetchedAt } = useAnalysis({
    query,
    reportStatus,
    limit: 400,
    refreshToken,
  })

  const summary = data?.summary
  const status = data?.status
  const events = data?.events ?? []

  // The grid scrolls inside its own pane, so show the whole triage queue
  // rather than an arbitrary top-N. Events arrive already sorted by priority.
  const worklist = events.filter((e) => e.priority.level !== 'LOW')
  const shown = worklist.length ? worklist : events

  const classRows = Object.entries(summary?.by_class ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
  const maxClass = Math.max(1, ...classRows.map(([, n]) => n))

  if (error) {
    return (
      <div className="surface">
        <div className="sheet">
          <Module title="Current analysis">
            <ErrorState error={error} onRetry={reload} what="the current analysis" />
          </Module>
        </div>
      </div>
    )
  }

  if (loading && !data) {
    return (
      <div className="surface">
        <div className="sheet">
          <Module title="Current analysis">
            <Loading label="Querying NASA FIRMS and assembling geographic evidence…" />
          </Module>
        </div>
      </div>
    )
  }

  return (
    <div className="surface surface-flush">
      <div className="ops">
        {status?.mode === 'snapshot' && (
          <Note kind="warn">
            <strong>Historical capture.</strong> {status.firms_message} Every record shown is a
            real past NASA detection — none of it is generated.
          </Note>
        )}

        {/* ── headline state ───────────────────────────────────────────── */}
        <div className="metrics metrics-6">
          <Metric
            label="Detections"
            value={int(summary?.total_events)}
            sub={`${region.label.split(' — ')[0]} · ${window.label}`}
          />
          <Metric
            label="Industrial"
            value={int(summary?.industrial_related)}
            sub="fire + persistent heat"
          />
          <Metric
            label="High priority"
            value={int(summary?.high_priority)}
            sub="triage first"
            tone="alarm"
          />
          <Metric
            label="Unresolved"
            value={int(summary?.low_confidence)}
            sub="low vote score or abstained"
            tone="warn"
          />
          <Metric
            label="Persistent"
            value={int(summary?.persistent_sources)}
            sub="recurring signature"
          />
          <Metric
            label="Total radiative"
            value={num(summary?.frp_total_mw, 0)}
            unit="MW"
            sub="sum of reported FRP"
          />
        </div>

        <div className="ops-main">
          {/* ── the worklist ───────────────────────────────────────────── */}
          <div className="ops-col">
            <Module
              className="ops-fill"
              title="Priority worklist"
              icon={<IconAlert />}
              actions={
                <button className="btn btn-xs" onClick={() => navigate('/explore')}>
                  Open map workspace →
                </button>
              }
              note={`${int(shown.length)} above LOW`}
              flush
            >
              <div className="gridwrap" style={{ flex: 1, minHeight: 0 }}>
                <table className="grid">
                  <thead>
                    <tr>
                      <th className="r">Pri</th>
                      <th>Likely source</th>
                      <th className="r">RF score</th>
                      <th>Acquired IST</th>
                      <th className="r">FRP MW</th>
                      <th>Nearest facility</th>
                      <th>Land cover</th>
                      <th className="r">Days</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.length === 0 && (
                      <tr>
                        <td colSpan={8} className="dim" style={{ height: 60, textAlign: 'center' }}>
                          No detections returned for this area and window.
                        </td>
                      </tr>
                    )}
                    {shown.map((item) => {
                      const nf = item.evidence.nearest_facility
                      return (
                        <tr
                          key={item.event.event_id}
                          className="hit"
                          onClick={() => navigate('/explore')}
                        >
                          <td className="r">
                            <Priority level={item.priority.level} score={item.priority.score} />
                          </td>
                          <td>
                            <ClassMark cls={classMap[item.classification.label]} />
                          </td>
                          <td className="num r">{pct(item.classification.confidence)}</td>
                          <td className="num dim">
                            {utcAndIst(item.event.acquired_at).ist.replace(' IST', '')}
                          </td>
                          <td className="num r">
                            {item.event.frp_mw === null ? (
                              <span className="na">n/r</span>
                            ) : (
                              num(item.event.frp_mw)
                            )}
                          </td>
                          <td className="dim">
                            {nf ? (
                              <>
                                <span className="num">
                                  {km(item.evidence.distance_to_nearest_facility_km)}
                                </span>{' '}
                                {nf.name || nf.category_label}
                              </>
                            ) : (
                              <span className="na">none in radius</span>
                            )}
                          </td>
                          <td className="dim">
                            {item.evidence.land_cover.category === 'unknown' ? (
                              <span className="na">unmapped</span>
                            ) : (
                              item.evidence.land_cover.label
                            )}
                          </td>
                          <td className="num r dim">
                            {item.evidence.recurrence.history_available
                              ? item.evidence.recurrence.distinct_days
                              : '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Module>

            {/* ── the chain, as a pipeline not prose ───────────────────── */}
            <Module title="Evidence chain" icon={<IconMethod />} note="per detection" flush>
              <div className="pipe">
                <PipeNode index="01" title="Detect" meta="NASA FIRMS">
                  Position, acquisition time, brightness temperature, radiative power. FIRMS
                  reports <em>where</em> heat is, not what is burning.
                </PipeNode>
                <PipeNode index="02" title="Locate" meta="OSM · haversine">
                  Distance and type of the nearest mapped industrial facility.
                </PipeNode>
                <PipeNode index="03" title="Ground" meta="OSM land use">
                  The land-use polygon containing the point, or <em>unknown</em>.
                </PipeNode>
                <PipeNode index="04" title="History" meta="strictly prior days">
                  How often this exact spot has burned before. A flare repeats; a crop fire does
                  not.
                </PipeNode>
                <PipeNode index="05" title="Classify" meta="Random Forest">
                  Likely source, RF vote score, and the factors that moved this prediction.
                </PipeNode>
                <PipeNode index="06" title="Triage" meta="weighted sum">
                  Transparent priority score. Persistence <em>lowers</em> it.
                </PipeNode>
              </div>
            </Module>
          </div>

          {/* ── distributions ──────────────────────────────────────────── */}
          <div className="ops-col">
            <Module title="Classification mix" icon={<IconModel />} note={`${int(summary?.total_events)} records`}>
              {classRows.length === 0 ? (
                <p className="dim sm">No detections in this window.</p>
              ) : (
                classRows.map(([id, n]) => {
                  const cls = classMap[id]
                  return (
                    <Bar
                      key={id}
                      label={
                        <>
                          <span className="code" style={{ color: cls?.color }}>
                            {cls?.code ?? '—'}
                          </span>
                          <span className="trunc xs">{cls?.label ?? id}</span>
                        </>
                      }
                      value={n}
                      max={maxClass}
                      display={int(n)}
                      color={cls?.color ?? 'var(--ink-4)'}
                      labelWidth={150}
                    />
                  )
                })
              )}
              <Provenance note="Counts are detections in this window, not distinct physical fires — one fire can be seen by several satellite passes." />
            </Module>

            <Module title="Triage distribution" icon={<IconGauge />}>
              {['HIGH', 'MEDIUM', 'LOW'].map((lvl) => (
                <Bar
                  key={lvl}
                  label={<Priority level={lvl} />}
                  value={summary?.by_priority?.[lvl] ?? 0}
                  max={Math.max(1, ...Object.values(summary?.by_priority ?? { a: 1 }))}
                  display={int(summary?.by_priority?.[lvl] ?? 0)}
                  color={
                    lvl === 'HIGH' ? 'var(--alarm)' : lvl === 'MEDIUM' ? 'var(--warn)' : 'var(--ink-4)'
                  }
                  labelWidth={56}
                />
              ))}
              <p className="xs dim" style={{ marginTop: 9, lineHeight: 1.5 }}>
                A flare that burns every day is routine and sinks. The same signal somewhere that
                has never burned before rises. That inversion is the difference between a
                detection feed and a triage tool.
              </p>
            </Module>

            <Module title="Acquisition" note={status?.mode === 'live' ? 'live' : 'historical'}>
              <dl className="kv">
                <dt>Products</dt>
                <dd className="m xs">{status?.firms_products_used?.join(', ') || '—'}</dd>
                <dt>Observed</dt>
                <dd className="m">{window.label}</dd>
                <dt>Retrieved</dt>
                <dd className="m xs">{fetchedAt ? fetchedAt.toLocaleString() : '—'}</dd>
                <dt>Geographic</dt>
                <dd className="xs">{status?.osm_message ?? '—'}</dd>
                <dt>Land cover</dt>
                <dd className="xs">{status?.land_cover_provider ?? '—'}</dd>
              </dl>
            </Module>
          </div>
        </div>

        <div>
          <Note kind="plain">
            FIRETRACE produces model-assisted likelihoods from satellite and open geographic
            data. It is not a confirmed fire diagnosis and requires human verification before any
            operational decision.
          </Note>
        </div>
      </div>
    </div>
  )
}
