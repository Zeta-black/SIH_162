import { api } from '../api.js'
import { useApi } from '../lib/useApi.js'
import { int } from '../lib/format.js'
import { ErrorState, Group, Loading, Metric, Module, Note } from '../components/ui.jsx'

function Row({ label, children }) {
  if (children === null || children === undefined || children === '') return null
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

function SourceCard({ source }) {
  return (
    <Group title={source.name}>
      <p className="sm" style={{ marginBottom: 12 }}>
        {source.role}
      </p>

      <dl className="kv">
        <Row label="Provider">{source.provider}</Row>
        <Row label="Type">{source.category}</Row>
        <Row label="Access">{source.access}</Row>
        {source.endpoint && (
          <Row label="Endpoint">
            <span className="m xs">{source.endpoint}</span>
          </Row>
        )}
        {source.observations_held != null && (
          <Row label="Records held">
            <span className="num">{int(source.observations_held)}</span> detections
          </Row>
        )}
        {source.features_held != null && (
          <Row label="Features held">
            <span className="num">{int(source.features_held)}</span> industrial features
          </Row>
        )}
        {source.polygons_in_snapshot != null && (
          <Row label="Polygons">
            <span className="num">{int(source.polygons_in_snapshot)}</span> in the offline snapshot
          </Row>
        )}
        {source.observation_period?.from && (
          <Row label="Period">
            <span className="m">
              {source.observation_period.from} → {source.observation_period.to}
            </span>
          </Row>
        )}
        {source.max_window_per_request && (
          <Row label="Request limit">{source.max_window_per_request}</Row>
        )}
        <Row label="Processing">{source.processing}</Row>
        <Row label="Licence">{source.licence}</Row>
      </dl>

      {source.is_not && (
        <div style={{ marginTop: 12 }}>
          <Note kind="warn">
            <strong>What this is not: </strong>
            {source.is_not}
          </Note>
        </div>
      )}

      {source.products?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="cmd-label">Products used</div>
          <div className="gridwrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Platform</th>
                  <th>Instrument</th>
                  <th className="r">Resolution</th>
                </tr>
              </thead>
              <tbody>
                {source.products.map((p) => (
                  <tr key={p.id}>
                    <td className="m xs">{p.id}</td>
                    <td>{p.platform}</td>
                    <td>{p.instrument}</td>
                    <td className="num">{p.resolution}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {source.fields_used?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="cmd-label">Fields consumed, with units</div>
          <div className="gridwrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Unit</th>
                </tr>
              </thead>
              <tbody>
                {source.fields_used.map((f) => (
                  <tr key={f.field}>
                    <td className="m xs">{f.field}</td>
                    <td className="dim">{f.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {source.tags_queried?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="cmd-label">OpenStreetMap tags queried</div>
          <div className="row wrap" style={{ gap: 5 }}>
            {source.tags_queried.map((t) => (
              <span key={t} className="m xs" style={{ background: 'var(--surface-inset)', padding: '2px 6px', borderRadius: 2 }}>
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {source.measured_coverage?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="cmd-label">Measured coverage gaps</div>
          <div className="gridwrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Area</th>
                  <th className="r">Unmapped</th>
                  <th>Consequence</th>
                </tr>
              </thead>
              <tbody>
                {source.measured_coverage.map((c) => (
                  <tr key={c.area}>
                    <td>{c.area}</td>
                    <td className="num" style={{ color: 'var(--danger)' }}>
                      {c.unknown_share}
                    </td>
                    <td className="dim sm">{c.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {source.caveats && (
        <p className="sm dim" style={{ marginTop: 12 }}>
          {source.caveats}
        </p>
      )}
    </Group>
  )
}

export default function DataSources() {
  const { data, error, loading, reload } = useApi(() => api.sources(), [])

  if (loading)
    return (
      <div className="surface">
        <div className="sheet">
          <Loading label="Reading data provenance…" />
        </div>
      </div>
    )
  if (error)
    return (
      <div className="surface">
        <div className="sheet">
          <ErrorState error={error} onRetry={reload} what="the data provenance record" />
        </div>
      </div>
    )

  const snapshot = data.snapshot
  const training = data.training_dataset

  return (
    <div className="surface">
      <div className="sheet">
        <header className="sheet-head">
          <h1>Data</h1>
          <p className="lede">
            Every source this system reads, what it contributes, and what it cannot tell us. The
            record below is read from the live store and files at request time, not written into
            the page.
          </p>
        </header>

        <div style={{ marginBottom: 22 }}>
          <Note kind="info">{data.statement}</Note>
        </div>

        <Group title="Sources">
          <div className="stack" style={{ gap: 16 }}>
            {data.sources.map((s) => (
              <SourceCard key={s.id} source={s} />
            ))}
          </div>
        </Group>

        {snapshot && (
          <Module title="Offline snapshot" note={`captured ${String(snapshot.captured_at).slice(0, 10)}`}>
            <Module title={snapshot.name}>
              <div className="metrics metrics-3" style={{ marginBottom: 14 }}>
                <Metric label="Detections" value={int(snapshot.events)} sub="real FIRMS records" />
                <Metric label="Facilities" value={int(snapshot.facilities)} sub="real OSM features" />
                <Metric label="Land-use polygons" value={int(snapshot.landuse_polygons)} sub="real OSM geometry" />
              </div>
              <dl className="kv">
                <Row label="What it is">{snapshot.what_it_is}</Row>
                <Row label="What it is not">{snapshot.what_it_is_not}</Row>
                <Row label="Products">{(snapshot.products ?? []).join(', ')}</Row>
                {snapshot.date_range?.from && (
                  <Row label="Period">
                    <span className="m">
                      {snapshot.date_range.from} → {snapshot.date_range.to}
                    </span>
                  </Row>
                )}
                <Row label="Regions">{(snapshot.regions ?? []).join(', ')}</Row>
              </dl>
            </Module>
          </Module>
        )}

        {training && (
          <Module title="Training dataset" note={`version ${training.dataset_version}`}>
            <Module>
              <div className="metrics metrics-3" style={{ marginBottom: 14 }}>
                <Metric label="Labelled rows" value={int(training.rows_labelled)} sub="used for training" />
                <Metric
                  label="Excluded"
                  value={int(training.rows_excluded_ambiguous)}
                  sub="ambiguous — deliberately unlabelled"
                  tone="warn"
                />
                <Metric
                  label="Regions"
                  value={int((training.regions ?? []).filter((r) => r.labelled > 0).length)}
                  sub="areas of interest contributing"
                />
              </div>

              <dl className="kv">
                <Row label="Observations">{training.observation_source}</Row>
                <Row label="Context">{training.context_source}</Row>
                <Row label="Labels">
                  <strong>{training.label_source}</strong>
                </Row>
                <Row label="Built">
                  <span className="m xs">{training.built_at}</span>
                </Row>
              </dl>

              <div style={{ marginTop: 14 }}>
                <div className="cmd-label">Class balance</div>
                <div className="gridwrap">
                  <table className="grid">
                    <thead>
                      <tr>
                        <th>Class</th>
                        <th className="r">Rows</th>
                        <th className="r">Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(training.label_counts ?? {})
                        .sort((a, b) => b[1] - a[1])
                        .map(([label, count]) => (
                          <tr key={label}>
                            <td className="m xs">{label}</td>
                            <td className="num">{int(count)}</td>
                            <td className="num dim">
                              {((count / training.rows_labelled) * 100).toFixed(1)}%
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div style={{ marginTop: 14 }}>
                <Note kind="warn">{training.caveat}</Note>
              </div>
            </Module>
          </Module>
        )}

        <Group title="Collection windows">
          <Module>
            <p className="sm" style={{ marginBottom: 12 }}>
              The FIRMS area API rejects any span outside 1–5 days, so a long observation period
              has to be assembled from consecutive 5-day requests. Those were made{' '}
              <strong>contiguous on purpose</strong>: five back-to-back requests give 25 unbroken
              days, which is what the recurrence features need. The same 25 days sampled at random
              across a year would show no persistence at all.
            </p>
            <div className="gridwrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Window</th>
                    <th>Start</th>
                    <th className="r">Days</th>
                    <th>Products</th>
                  </tr>
                </thead>
                <tbody>
                  {(training?.windows ?? []).map((w) => (
                    <tr key={w.id}>
                      <td className="m xs">{w.id}</td>
                      <td className="num">{w.start || 'most recent'}</td>
                      <td className="num">{w.days}</td>
                      <td className="dim sm">{(w.products ?? []).join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Module>
        </Group>

        <p className="sm faint">Provenance record generated {data.generated_at}</p>
      </div>
    </div>
  )
}
