import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useApi } from '../lib/useApi.js'
import { coords, int, km, num, utcAndIst } from '../lib/format.js'
import {
  ClassMark,
  ErrorState,
  Group,
  Loading,
  Metric,
  Module,
  Note,
  Priority,
  Provenance,
} from '../components/ui.jsx'
import { IconAlert, IconGauge, IconRefresh, IconReplay } from '../components/icons.jsx'
import IncidentPanel, { AlertChip, StatusChip } from '../components/IncidentPanel.jsx'

/**
 * Demo / Replay.
 *
 * A judge picks a real historical detection, looks at the raw source record,
 * presses REPLAY, and watches the actual backend pipeline run on it — stage by
 * stage, with the duration each stage really took.
 *
 * Nothing on this screen is animated to look like progress. The stage list is
 * rendered from the timings the backend reports after the run, and the result
 * and alert level come from the same functions the live dashboard calls. If the
 * pipeline were broken, this page would show it rather than hide it.
 */

const SCENARIO_ORDER = [
  'CRITICAL_PRIORITY_EVENT',
  'HIGH_PRIORITY_EVENT',
  'MULTI_DETECTION_EVENT',
  'REPEATED_DETECTIONS',
  'PERSISTENT_FLARE',
  'HIGH_FRP_EVENT',
  'HIGH_CONFIDENCE_EVENT',
  'LOW_CONFIDENCE_EVENT',
  'ABSTENTION_CASE',
  'ISOLATED_DETECTION',
  'LOW_PRIORITY_EVENT',
  'DUPLICATE_DATA_TEST',
]

function Field({ label, value, mono = true }) {
  return (
    <div className="rp-f">
      <span className="rp-fk">{label}</span>
      <span className={mono ? 'rp-fv m' : 'rp-fv'}>{value ?? '—'}</span>
    </div>
  )
}

/** One pipeline stage, with the duration it actually took. */
function StageRow({ stage, max }) {
  const width = max > 0 ? Math.max(1.5, (stage.duration_ms / max) * 100) : 0
  return (
    <div className={`rp-st${stage.ok ? '' : ' rp-st-bad'}`}>
      <div className="rp-st-head">
        <span className="rp-st-name m">{stage.stage}</span>
        <span className="rp-st-ms m">{num(stage.duration_ms, 2)} ms</span>
      </div>
      <div className="rp-st-bar">
        <span className="rp-st-fill" style={{ width: `${width}%` }} />
      </div>
      <div className="rp-st-detail">{stage.error ? stage.error : stage.detail}</div>
    </div>
  )
}

export default function Replay() {
  const { data, error, loading, reload } = useApi(() => api.replayCatalogue(), [])
  const [selectedId, setSelectedId] = useState(null)
  const [run, setRun] = useState(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState(null)
  const [incident, setIncident] = useState(null)

  const cases = useMemo(() => data?.cases ?? [], [data])

  const grouped = useMemo(() => {
    const byScenario = {}
    for (const c of cases) {
      const bucket = byScenario[c.scenario] ?? []
      bucket.push(c)
      byScenario[c.scenario] = bucket
    }
    const order = [
      ...SCENARIO_ORDER.filter((s) => byScenario[s]),
      ...Object.keys(byScenario).filter((s) => !SCENARIO_ORDER.includes(s)),
    ]
    return order.map((id) => ({ id, cases: byScenario[id] }))
  }, [cases])

  // Default to the first case so the screen is never empty on arrival.
  useEffect(() => {
    if (!selectedId && cases.length) setSelectedId(cases[0].case_id)
  }, [cases, selectedId])

  const selected = useMemo(
    () => cases.find((c) => c.case_id === selectedId) ?? null,
    [cases, selectedId],
  )

  // Selecting a different case clears the previous run: showing case B's
  // source record beside case A's result would be actively misleading.
  useEffect(() => {
    setRun(null)
    setRunError(null)
    setIncident(null)
  }, [selectedId])

  const doReplay = async () => {
    if (!selected) return
    setRunning(true)
    setRunError(null)
    try {
      const result = await api.replayRun(selected.case_id, { persist: true })
      setRun(result)
      setIncident(result.incident ?? null)
    } catch (err) {
      setRunError(err)
      setRun(null)
    } finally {
      setRunning(false)
    }
  }

  if (error) {
    return (
      <div className="surface">
        <div className="sheet">
          <ErrorState error={error} onRetry={reload} what="the replay catalogue" />
        </div>
      </div>
    )
  }
  if (loading && !data) {
    return (
      <div className="surface">
        <div className="sheet">
          <Loading label="Deriving replay cases from the historical snapshot…" />
        </div>
      </div>
    )
  }
  if (!data?.available) {
    return (
      <div className="surface">
        <div className="sheet">
          <Note kind="warn">
            {data?.note ?? 'No historical snapshot is present, so there is nothing to replay.'}
          </Note>
        </div>
      </div>
    )
  }

  const maxStageMs = run ? Math.max(...run.stages.map((s) => s.duration_ms)) : 0
  const result = run?.result
  const latency = run?.latency

  return (
    <div className="surface">
      <div className="sheet">
        <header className="sheet-head">
          <div>
            <h1>Demo / Replay</h1>
            <p className="sm dim" style={{ margin: '3px 0 0' }}>
              Select a verified historical detection and run it back through the real
              processing pipeline. {data.case_count} cases, all from{' '}
              {int(data.source.detections_available)} genuine NASA FIRMS observations.
            </p>
          </div>
        </header>

        <Note kind="info">
          <strong>These are real observations with unknown ground truth.</strong> Every case
          points at an actual FIRMS detection captured between{' '}
          {data.source.date_range?.from} and {data.source.date_range?.to}. No verified field
          report exists for any of them, so the replay shows what our system concludes — not
          what was confirmed to be burning.
        </Note>

        <div className="rp-grid">
          {/* ── 1. SELECT ─────────────────────────────────────────────── */}
          <div className="rp-list">
            <Module title="1 · Select historical event" note={`${cases.length} cases`} flush>
              <div className="rp-scroll">
                {grouped.map((g) => (
                  <div key={g.id}>
                    <div className="rp-grp">{g.cases[0].scenario_title}</div>
                    {g.cases.map((c) => (
                      <button
                        key={c.case_id}
                        className={`rp-case${c.case_id === selectedId ? ' rp-case-on' : ''}`}
                        onClick={() => setSelectedId(c.case_id)}
                      >
                        <span className="rp-case-id m">{c.event_id}</span>
                        <span className="rp-case-meta">
                          {c.date} · {c.detection_count} det
                          {c.frp_mw != null ? ` · ${num(c.frp_mw, 1)} MW` : ''}
                        </span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </Module>
          </div>

          {/* ── 2-7. THE RUN ──────────────────────────────────────────── */}
          <div className="col">
            {selected && (
              <Module
                title="2 · Source record"
                icon={<IconReplay />}
                note={selected.scenario_title}
                actions={
                  <button className="btn btn-go" disabled={running} onClick={doReplay}>
                    {running && <span className="spin" style={{ borderTopColor: '#fff' }} />}
                    {running ? 'Replaying…' : 'Replay event'}
                  </button>
                }
              >
                <p className="sm dim" style={{ margin: '0 0 9px' }}>
                  {selected.scenario_question}
                </p>
                <div className="rp-fields">
                  <Field label="Event ID" value={selected.event_id} />
                  <Field label="Date" value={selected.date} />
                  <Field label="Time (UTC)" value={selected.time_utc} />
                  <Field label="Latitude" value={num(selected.latitude, 5)} />
                  <Field label="Longitude" value={num(selected.longitude, 5)} />
                  <Field label="Source" value={selected.source} />
                  <Field label="Satellite" value={selected.satellite} />
                  <Field label="Instrument" value={selected.instrument} />
                  <Field label="FIRMS confidence" value={selected.confidence} />
                  <Field
                    label="FRP"
                    value={selected.frp_mw != null ? `${num(selected.frp_mw, 2)} MW` : '—'}
                  />
                  <Field
                    label="Brightness"
                    value={selected.brightness_k != null ? `${num(selected.brightness_k, 1)} K` : '—'}
                  />
                  <Field label="Detections" value={int(selected.detection_count)} />
                </div>
                <div className="rp-gt">
                  GROUND TRUTH: <strong>{selected.ground_truth}</strong>
                  <span className="xs faint"> — {selected.ground_truth_note}</span>
                </div>
                <p className="xs faint" style={{ margin: '8px 0 0' }}>
                  Retrieved by: <span className="m">{selected.raw_source_reference}</span>
                </p>
              </Module>
            )}

            {runError && (
              <Note kind="alarm">
                <strong>The replay failed.</strong> {runError.message}
              </Note>
            )}

            {running && !run && (
              <Module title="3 · Processing">
                <div className="state">
                  <span className="spin spin-lg" />
                  <p className="sm">
                    Running the pipeline on the backend. Stage timings appear when the run
                    completes — they are measured, so there is nothing truthful to show
                    until then.
                  </p>
                </div>
              </Module>
            )}

            {run && (
              <>
                {/* ── 3. PROCESSING TIMELINE ────────────────────────── */}
                <Module
                  title="3 · Processing timeline"
                  icon={<IconRefresh />}
                  note={`${num(run.run.total_ms, 1)} ms end to end`}
                >
                  <div className="rp-stages">
                    {run.stages.map((s) => (
                      <StageRow key={s.stage} stage={s} max={maxStageMs} />
                    ))}
                  </div>
                  <div className="rp-counts">
                    <span>
                      <b>{int(run.counts.ingested)}</b> ingested
                    </span>
                    <span>
                      <b>{int(run.counts.validated)}</b> validated
                    </span>
                    <span>
                      <b>{int(run.counts.rejected)}</b> rejected
                    </span>
                    <span>
                      <b>{int(run.counts.duplicates_removed)}</b> duplicates dropped
                    </span>
                    <span>
                      <b>{int(run.counts.fire_events)}</b> fire events formed
                    </span>
                  </div>
                </Module>

                {/* ── LATENCY ───────────────────────────────────────── */}
                {latency && (
                  <Group title="Latency" note="measured during this run">
                    <div className="mod">
                      <div className="mod-head">
                        <span className="mod-title">Source</span>
                      </div>
                      <div className="mod-body">
                        <div className="rp-fields">
                          <Field
                            label="Observation"
                            value={utcAndIst(latency.source.observation_at).ist}
                          />
                          <Field
                            label="Available to us"
                            value={utcAndIst(latency.source.available_to_us_at).ist}
                          />
                        </div>
                        {!latency.source.measurable && (
                          <div className="rp-nm">NOT A LATENCY MEASUREMENT</div>
                        )}
                        <p className="xs faint" style={{ margin: '8px 0 0', lineHeight: 1.5 }}>
                          {latency.source.caveat}
                        </p>
                      </div>
                    </div>

                    <div className="mod" style={{ marginTop: 10 }}>
                      <div className="mod-head">
                        <span className="mod-title">Our platform</span>
                        <span className="mod-note">excludes NASA and Overpass network time</span>
                      </div>
                      <div className="mod-body">
                        <div className="metrics metrics-4">
                          <Metric
                            label="Ingestion"
                            value={num(latency.platform.ingestion_ms, 2)}
                            unit="ms"
                          />
                          <Metric
                            label="Validation"
                            value={num(latency.platform.validation_ms, 2)}
                            unit="ms"
                          />
                          <Metric
                            label="Enrichment"
                            value={num(latency.platform.enrichment_ms, 2)}
                            unit="ms"
                          />
                          <Metric
                            label="Features"
                            value={num(latency.platform.feature_extraction_ms, 2)}
                            unit="ms"
                          />
                          <Metric
                            label="ML inference"
                            value={num(latency.platform.ml_inference_ms, 2)}
                            unit="ms"
                          />
                          <Metric
                            label="Risk / priority"
                            value={num(latency.platform.risk_priority_ms, 2)}
                            unit="ms"
                          />
                          <Metric
                            label="Clustering"
                            value={num(latency.platform.clustering_ms, 2)}
                            unit="ms"
                          />
                          <Metric
                            label="Alert"
                            value={num(latency.platform.alert_generation_ms, 2)}
                            unit="ms"
                          />
                        </div>
                        <div className="rp-e2e">
                          <span className="cmd-label">End-to-end platform</span>
                          <span className="rp-e2e-v m">
                            {num(latency.end_to_end_platform_ms, 1)} ms
                          </span>
                        </div>
                        <p className="xs faint" style={{ margin: '7px 0 0' }}>
                          {latency.note}
                        </p>
                      </div>
                    </div>
                  </Group>
                )}

                {/* ── 4. RESULT ─────────────────────────────────────── */}
                {result?.formed_event && (
                  <Module
                    title="4 · Result"
                    icon={<IconGauge />}
                    note={result.event_id}
                  >
                    <div className="between" style={{ marginBottom: 10 }}>
                      <ClassMark cls={result.classification} />
                      <Priority level={result.priority_level} score={result.priority_score} />
                    </div>

                    <div className="rp-fields">
                      <Field label="Location" value={coords(result.latitude, result.longitude)} />
                      <Field label="Detections" value={int(result.detection_count)} />
                      <Field
                        label="First detected"
                        value={utcAndIst(result.first_detected).ist}
                      />
                      <Field label="Latest detected" value={utcAndIst(result.last_detected).ist} />
                      <Field
                        label="Peak FRP"
                        value={result.frp_max_mw != null ? `${num(result.frp_max_mw, 2)} MW` : '—'}
                      />
                      <Field
                        label="Peak brightness"
                        value={
                          result.brightness_max_k != null
                            ? `${num(result.brightness_max_k, 1)} K`
                            : '—'
                        }
                      />
                      <Field label="Nearest facility" value={result.nearest_facility_name} mono={false} />
                      <Field label="Distance" value={km(result.nearest_facility_km)} />
                      <Field label="Land cover" value={result.land_cover} mono={false} />
                      <Field label="Persistent source" value={result.persistent ? 'Yes' : 'No'} />
                      <Field label="Satellites" value={(result.satellites ?? []).join(', ')} />
                      <Field label="Ground truth" value={result.ground_truth} />
                    </div>

                    {/* WHY THIS PRIORITY — the actual weighted components. */}
                    {result.priority_explanation && (
                      <div className="rp-why">
                        <div className="cmd-label" style={{ marginBottom: 6 }}>
                          Why this priority?
                        </div>
                        {Object.entries(result.priority_explanation.components).map(
                          ([name, value]) => {
                            const weight = result.priority_explanation.weights?.[name] ?? 0
                            return (
                              <div className="rp-w" key={name}>
                                <span className="rp-w-k">{name.replace(/_/g, ' ')}</span>
                                <span className="rp-w-bar">
                                  <span
                                    className="rp-w-fill"
                                    style={{ width: `${Math.round(value * 100)}%` }}
                                  />
                                </span>
                                <span className="rp-w-v m">{num(value, 3)}</span>
                                <span className="rp-w-x m">x{num(weight, 2)}</span>
                              </div>
                            )
                          },
                        )}
                        <p className="xs faint" style={{ margin: '7px 0 0', lineHeight: 1.5 }}>
                          {result.priority_explanation.note}
                        </p>
                      </div>
                    )}

                    {result.risk_factors?.length > 0 && (
                      <div style={{ marginTop: 10 }}>
                        <div className="cmd-label" style={{ marginBottom: 4 }}>
                          Risk factors
                        </div>
                        <ul className="rp-ul">
                          {result.risk_factors.map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </Module>
                )}

                {/* ── 5. ALERT ──────────────────────────────────────── */}
                <Module
                  title="5 · Alert"
                  icon={<IconAlert />}
                  note={run.persistence?.skipped ? 'not persisted' : 'persisted'}
                >
                  {result?.alert_raised ? (
                    <>
                      <div className="between" style={{ marginBottom: 9 }}>
                        <AlertChip level={result.alert_level} />
                        {incident && <StatusChip status={incident.status} />}
                      </div>
                      <div className="cmd-label" style={{ marginBottom: 4 }}>
                        Why this alerted
                      </div>
                      <ul className="rp-ul">
                        {result.alert_reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <Note kind="plain">
                      <strong>No alert was raised.</strong> The alert rule was evaluated on this
                      event and did not fire. A system that alerted on everything would train
                      its operators to ignore it.
                    </Note>
                  )}

                  {run.persistence && !run.persistence.skipped && (
                    <div className="rp-counts" style={{ marginTop: 10 }}>
                      <span>
                        <b>{int(run.persistence.detections_written)}</b> detections stored
                      </span>
                      <span>
                        <b>{int(run.persistence.created)}</b> incidents created
                      </span>
                      <span>
                        <b>{int(run.persistence.updated)}</b> updated
                      </span>
                      {run.persistence.re_alerted > 0 && (
                        <span>
                          <b>{int(run.persistence.re_alerted)}</b> re-alerted while closed
                        </span>
                      )}
                    </div>
                  )}

                  {run.persistence?.created === 0 && run.persistence?.updated > 0 && (
                    <Note kind="info">
                      <strong>Replayed again — no second alert.</strong> This event already had
                      an incident, so it was updated rather than raised again. One fire, one
                      incident.
                    </Note>
                  )}
                </Module>

                {/* ── 6-7. OPERATOR WORKFLOW ────────────────────────── */}
                {incident && (
                  <IncidentPanel
                    incident={incident}
                    onChanged={(updated) => setIncident(updated)}
                  />
                )}

                {/* ── EVIDENCE ──────────────────────────────────────── */}
                {run.factors?.length > 0 && (
                  <Module title="Why this classification" note="decision-path attribution">
                    <ul className="rp-ul">
                      {run.factors.slice(0, 8).map((f, i) => (
                        <li key={i} className={`fac fac-${f.direction}`}>
                          {f.text}
                        </li>
                      ))}
                    </ul>
                  </Module>
                )}

                <Provenance
                  source="NASA FIRMS (historical snapshot) + OpenStreetMap"
                  observed={selected?.acquired_at}
                  processing="Replayed through the live pipeline code on this machine"
                  note={run.disclaimer}
                />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
