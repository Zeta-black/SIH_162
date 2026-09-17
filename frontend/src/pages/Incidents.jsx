import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useMeta, useQueryState } from '../App.jsx'
import { useApi, useDebounced } from '../lib/useApi.js'
import { int, km, num, pct, utcAndIst } from '../lib/format.js'
import {
  Bar,
  ClassMark,
  ErrorState,
  Loading,
  Metric,
  Module,
  Note,
  Priority,
  Provenance,
} from '../components/ui.jsx'
import { IconAlert, IconGauge, IconMap } from '../components/icons.jsx'
import IncidentPanel, { AlertChip, StatusChip } from '../components/IncidentPanel.jsx'

/**
 * Fire events, not pixels.
 *
 * A satellite reports hot pixels. One fire across three overpasses is a dozen
 * FIRMS rows, and listing all twelve makes an operator do the grouping by eye.
 * This screen shows the incident: how many detections compose it, over what
 * window, how far it has spread, and why it scored the priority it did.
 */
export default function Incidents() {
  const { query, refreshToken } = useQueryState()
  const { classMap } = useMeta()
  const settled = useDebounced(query, 350)
  const [selected, setSelected] = useState(null)
  const [priorityFilter, setPriorityFilter] = useState([])
  const [multiOnly, setMultiOnly] = useState(false)
  const [incident, setIncident] = useState(null)
  const [loadingIncident, setLoadingIncident] = useState(false)

  const { data, error, loading, reload } = useApi(
    () => api.events({ ...settled, limit: 400 }),
    [settled.bbox, settled.days, settled.mode, refreshToken],
    { keepPrevious: true },
  )

  const events = useMemo(() => {
    const all = data?.events ?? []
    return all.filter((e) => {
      if (priorityFilter.length && !priorityFilter.includes(e.priority_level)) return false
      if (multiOnly && e.detection_count < 2) return false
      return true
    })
  }, [data, priorityFilter, multiOnly])

  const detail = useMemo(
    () => events.find((e) => e.event_id === selected) ?? null,
    [events, selected],
  )

  // Most fire events never cross the alert rule and so have no incident record.
  // A 404 here is the normal case, not an error.
  useEffect(() => {
    if (!selected) {
      setIncident(null)
      return
    }
    let cancelled = false
    setLoadingIncident(true)
    api
      .incident(selected)
      .then((r) => !cancelled && setIncident(r))
      .catch(() => !cancelled && setIncident(null))
      .finally(() => !cancelled && setLoadingIncident(false))
    return () => {
      cancelled = true
    }
  }, [selected])

  // One request for the whole queue's incident state, so each row can show its
  // workflow status without a lookup per row.
  const queue = useApi(() => api.incidents({ limit: 500 }), [refreshToken, data])
  const incidentIndex = useMemo(() => {
    const out = {}
    for (const i of queue.data?.incidents ?? []) out[i.event_id] = i
    return out
  }, [queue.data])

  const s = data?.summary
  const cfg = data?.config

  if (error) {
    return (
      <div className="surface">
        <div className="sheet">
          <Module title="Fire events">
            <ErrorState error={error} onRetry={reload} what="fire events" />
          </Module>
        </div>
      </div>
    )
  }
  if (loading && !data) {
    return (
      <div className="surface">
        <div className="sheet">
          <Module title="Fire events">
            <Loading label="Grouping detections into fire events…" />
          </Module>
        </div>
      </div>
    )
  }

  const togglePriority = (p) =>
    setPriorityFilter((f) => (f.includes(p) ? f.filter((x) => x !== p) : [...f, p]))

  return (
    <div className="surface surface-flush">
      <div className="ops">
        {/* ── what clustering did ──────────────────────────────────────── */}
        <div className="metrics metrics-6">
          <Metric
            label="Satellite detections"
            value={int(s?.detections)}
            sub="raw FIRMS pixels"
          />
          <Metric
            label="Fire events"
            value={int(s?.events)}
            sub="after grouping"
          />
          <Metric
            label="Corroborated"
            value={int(s?.multi_detection_events)}
            sub="2+ detections"
          />
          <Metric
            label="Largest event"
            value={int(s?.largest_event_detections)}
            sub="detections in one event"
          />
          <Metric
            label="High priority"
            value={int(s?.by_priority?.HIGH)}
            sub="triage first"
            tone="alarm"
          />
          <Metric
            label="Compression"
            value={s?.compression ?? '—'}
            unit="×"
            sub="detections per event"
          />
        </div>

        <div className="ops-main">
          {/* ── incident queue ─────────────────────────────────────────── */}
          <div className="ops-col">
            <Module
              className="ops-fill"
              title="Fire event queue"
              icon={<IconAlert />}
              actions={
                <div className="row" style={{ gap: 6 }}>
                  {['HIGH', 'MEDIUM', 'LOW'].map((p) => (
                    <button
                      key={p}
                      className="btn btn-xs"
                      aria-pressed={priorityFilter.includes(p)}
                      style={
                        priorityFilter.includes(p)
                          ? { background: 'var(--ink)', color: '#fff', borderColor: 'var(--ink)' }
                          : undefined
                      }
                      onClick={() => togglePriority(p)}
                    >
                      {p}
                    </button>
                  ))}
                  <button
                    className="btn btn-xs"
                    aria-pressed={multiOnly}
                    style={
                      multiOnly
                        ? { background: 'var(--ink)', color: '#fff', borderColor: 'var(--ink)' }
                        : undefined
                    }
                    onClick={() => setMultiOnly((v) => !v)}
                    title="Hide single-detection events that no second pass has corroborated"
                  >
                    Corroborated only
                  </button>
                </div>
              }
              flush
            >
              <div className="gridwrap" style={{ flex: 1, minHeight: 0 }}>
                <table className="grid">
                  <thead>
                    <tr>
                      <th className="r">Pri</th>
                      <th>Status</th>
                      <th>Event ID</th>
                      <th>Likely source</th>
                      <th className="r">Det</th>
                      <th className="r">Passes</th>
                      <th className="r">Duration</th>
                      <th className="r">Spread</th>
                      <th className="r">FRP MW</th>
                      <th>Nearest facility</th>
                      <th>First detected IST</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.length === 0 && (
                      <tr>
                        <td colSpan={11} className="dim" style={{ height: 56, textAlign: 'center' }}>
                          No fire events match the current filters.
                        </td>
                      </tr>
                    )}
                    {events.map((e) => (
                      <tr
                        key={e.event_id}
                        className={`hit${e.event_id === selected ? ' sel' : ''}`}
                        onClick={() => setSelected(e.event_id)}
                      >
                        <td className="r">
                          <Priority level={e.priority_level} score={e.priority_score} />
                        </td>
                        <td>
                          {incidentIndex[e.event_id] ? (
                            <StatusChip status={incidentIndex[e.event_id].status} />
                          ) : (
                            <span className="na xs">no alert</span>
                          )}
                        </td>
                        <td className="num">{e.event_id}</td>
                        <td>
                          <ClassMark cls={classMap[e.label]} />
                        </td>
                        <td className="num r">{e.detection_count}</td>
                        <td className="num r dim">{e.distinct_passes}</td>
                        <td className="num r dim">
                          {e.duration_hours >= 1
                            ? `${num(e.duration_hours, 1)} h`
                            : `${Math.round(e.duration_hours * 60)} m`}
                        </td>
                        <td className="num r dim">{num(e.spread_km, 1)} km</td>
                        <td className="num r">
                          {e.frp_total_mw === null ? (
                            <span className="na">n/r</span>
                          ) : (
                            num(e.frp_total_mw, 1)
                          )}
                        </td>
                        <td className="dim trunc" style={{ maxWidth: 190 }}>
                          {e.nearest_facility_name ? (
                            <>
                              <span className="num">{km(e.nearest_facility_km)}</span>{' '}
                              {e.nearest_facility_name}
                            </>
                          ) : (
                            <span className="na">none in radius</span>
                          )}
                        </td>
                        <td className="num dim">
                          {utcAndIst(e.first_detected).ist.replace(' IST', '')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Module>
          </div>

          {/* ── why this event scored what it did ──────────────────────── */}
          <div className="ops-col">
            {detail ? (
              <>
                <Module
                  title={detail.event_id}
                  icon={<IconAlert />}
                  note={`${detail.detection_count} detections`}
                >
                  <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                    <span className="swatch" style={{ background: classMap[detail.label]?.color, width: 11, height: 11 }} />
                    <span style={{ fontSize: 15, fontWeight: 650 }}>{detail.label_display}</span>
                  </div>
                  <div className="between" style={{ marginBottom: 8 }}>
                    <span className="dim xs">Priority</span>
                    <span className="row" style={{ gap: 6 }}>
                      {incident?.alert_level && <AlertChip level={incident.alert_level} />}
                      <Priority level={detail.priority_level} score={detail.priority_score} />
                    </span>
                  </div>

                  <dl className="kv">
                    <dt>Detections</dt>
                    <dd className="m">
                      {detail.detection_count} across {detail.distinct_passes} pass
                      {detail.distinct_passes === 1 ? '' : 'es'}
                    </dd>
                    <dt>Class agreement</dt>
                    <dd className="m">
                      {pct(detail.label_agreement)} of member detections
                    </dd>
                    <dt>Window</dt>
                    <dd className="m xs">
                      {utcAndIst(detail.first_detected).ist}
                      <br />→ {utcAndIst(detail.last_detected).ist}
                    </dd>
                    <dt>Duration</dt>
                    <dd className="m">{num(detail.duration_hours, 2)} h</dd>
                    <dt>Spread</dt>
                    <dd className="m">{num(detail.spread_km, 2)} km</dd>
                    <dt>Platforms</dt>
                    <dd className="m xs">{detail.satellites.join(', ') || '—'}</dd>
                    <dt>Products</dt>
                    <dd className="m xs">{detail.products.join(', ')}</dd>
                    <dt>Radiative power</dt>
                    <dd className="m">
                      {detail.frp_total_mw === null ? (
                        <span className="na">not reported</span>
                      ) : (
                        `${num(detail.frp_total_mw, 1)} MW total · ${num(detail.frp_max_mw, 1)} peak`
                      )}
                    </dd>
                    <dt>Land cover</dt>
                    <dd>{detail.land_cover}</dd>
                    <dt>Centroid</dt>
                    <dd className="m xs">
                      {num(detail.latitude, 4)}, {num(detail.longitude, 4)}
                    </dd>
                  </dl>
                </Module>

                {loadingIncident ? (
                  <Module title="Response">
                    <div className="row dim sm">
                      <span className="spin" /> Checking incident record…
                    </div>
                  </Module>
                ) : incident ? (
                  <IncidentPanel incident={incident} onChanged={setIncident} />
                ) : (
                  <Module title="Response">
                    <p className="dim sm">
                      This fire event did not cross the alert rule, so no incident was raised and
                      there is nothing to action. Most events are in this state — alerting on
                      everything would be alerting on nothing.
                    </p>
                  </Module>
                )}

                <Module title={`Why ${detail.priority_level} priority`} icon={<IconGauge />}>
                  <ul style={{ margin: 0, paddingLeft: 16, lineHeight: 1.7, fontSize: 11.5 }}>
                    {detail.risk_factors.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                  <Provenance note="Every line is generated from a measured value on this event. A condition that does not hold produces no line." />
                </Module>
              </>
            ) : (
              <Module title="Event detail">
                <p className="dim sm">
                  Select a fire event to see how many satellite detections compose it, over what
                  window, and the measured reasons behind its priority.
                </p>
              </Module>
            )}

            <Module title="Grouping rule" icon={<IconMap />} note="how events are formed">
              <dl className="kv">
                <dt>Join radius</dt>
                <dd className="m">{cfg?.radius_km} km</dd>
                <dt>Join window</dt>
                <dd className="m">{cfg?.window_hours} h</dd>
                <dt>Method</dt>
                <dd className="xs">{cfg?.method}</dd>
              </dl>
              <p className="xs dim" style={{ marginTop: 9, lineHeight: 1.5 }}>
                {cfg?.rule}
              </p>
              <p className="xs faint" style={{ marginTop: 7, lineHeight: 1.5 }}>
                {cfg?.pixel_note}
              </p>
            </Module>

            <Module title="Class mix across events">
              {Object.entries(s?.by_class ?? {})
                .sort((a, b) => b[1] - a[1])
                .map(([id, n]) => {
                  const c = classMap[id]
                  return (
                    <Bar
                      key={id}
                      label={
                        <>
                          <span className="code" style={{ color: c?.color }}>
                            {c?.code ?? '—'}
                          </span>
                          <span className="trunc xs">{c?.label ?? id}</span>
                        </>
                      }
                      value={n}
                      max={Math.max(1, ...Object.values(s?.by_class ?? { a: 1 }))}
                      display={int(n)}
                      color={c?.color ?? 'var(--ink-4)'}
                      labelWidth={140}
                    />
                  )
                })}
            </Module>
          </div>
        </div>

        <Note kind="plain">
          <strong>{int(s?.detections)} satellite detections resolve to {int(s?.events)} fire
          events.</strong>{' '}
          A detection is a hot pixel, not a fire — one fire seen across several overpasses
          produces several detections. Grouping them is what turns a pixel feed into an incident
          queue an operator can work through.
        </Note>
      </div>
    </div>
  )
}
