import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useMeta } from '../App.jsx'
import { useApi } from '../lib/useApi.js'
import { num, pct } from '../lib/format.js'
import { ErrorState, Group, Loading, Module, Note, PipeNode } from '../components/ui.jsx'

export default function Method() {
  const { meta } = useMeta()
  const { data, error, loading, reload } = useApi(() => api.modelInfo(), [])

  if (loading)
    return (
      <div className="surface">
        <div className="sheet">
          <Loading label="Loading method record…" />
        </div>
      </div>
    )
  if (error)
    return (
      <div className="surface">
        <div className="sheet">
          <ErrorState error={error} onRetry={reload} what="the method record" />
        </div>
      </div>
    )

  const priority = meta?.priority ?? {}
  const cfg = meta?.feature_config ?? {}
  const thresholds = meta?.confidence_thresholds ?? {}
  const policy = data?.label_policy ?? {}

  return (
    <div className="surface">
      <div className="sheet">
        <header className="sheet-head">
          <h1>Method</h1>
          <p className="lede">
            How a satellite detection becomes a classification with reasoning attached, and what
            the system deliberately refuses to do.
          </p>
        </header>

        {/* ── the pipeline ───────────────────────────────────────────── */}
        <Group title="Processing pipeline">
          <Module>
            <div className="pipe">
              <PipeNode index="1" title="Detect" meta="NASA FIRMS · VIIRS 375 m, MODIS 1 km">
                Thermal anomalies are pulled server-side for the selected area and window. VIIRS
                and MODIS publish different column layouts and different confidence encodings, so
                each is mapped onto one internal schema. Fields a product does not supply are
                recorded as unavailable rather than imputed.
              </PipeNode>

              <PipeNode index="2" title="Locate" meta={`OpenStreetMap · search radius ${cfg.facility_search_radius_km} km`}>
                Each detection is matched against mapped industrial facilities — refineries,
                power plants, steel works, chemical plants, mines. Distance uses the haversine
                formula on a spherical Earth, not degree subtraction. A detection within{' '}
                {cfg.facility_onsite_km} km is treated as on the facility footprint.
              </PipeNode>

              <PipeNode index="3" title="Contextualise" meta="OpenStreetMap land use · point-in-polygon">
                The land-use polygon containing the detection gives cropland, forest, industrial
                and so on. Where no polygon covers the point the answer is <em>unknown</em> — in
                rural India that is common, and it is reported rather than guessed.
              </PipeNode>

              <PipeNode
                index="4"
                title="Compare against history"
                meta={`radius ${cfg.recurrence_radius_km} km · lookback ${cfg.recurrence_lookback_days} days`}
              >
                How many earlier days has this exact spot burned on? This is the signal that
                separates a flare stack from a fire: routine flaring repeats, an accident does
                not. Only detections strictly <em>earlier</em> than the one being scored are
                counted, so a historical row is built from what was knowable at the time.
              </PipeNode>

              <PipeNode index="5" title="Classify" meta={`Random Forest · ${data?.n_features ?? '—'} features`}>
                One feature pipeline serves both training and live inference, so they cannot
                drift. The forest returns a probability per class.{' '}
                <Link to="/model">See how it was validated →</Link>
              </PipeNode>

              <PipeNode index="6" title="Explain" meta="decision-path decomposition, per detection">
                Each tree&apos;s path for that sample is walked and the probability change at every
                split is attributed to the splitting feature. These are the factors that moved{' '}
                <em>this</em> output — not global importance, and not a causal claim about the
                fire.
              </PipeNode>

              <PipeNode index="7" title="Prioritise" meta="transparent weighted sum">
                A triage score combines confidence, class severity, thermal severity, industrial
                proximity, abnormality and recency. Every component and weight is returned with
                the score.
              </PipeNode>

              <PipeNode index="8" title="Verify" meta="human in the loop">
                Output is a ranked worklist with evidence attached, for a person to act on. The
                system never asserts a confirmed diagnosis.
              </PipeNode>
            </div>
          </Module>
        </Group>

        {/* ── classes ────────────────────────────────────────────────── */}
        <Group title="What the classes mean">
          <Module flush>
            <div className="gridwrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Class</th>
                    <th>Signature</th>
                    <th>Trained</th>
                  </tr>
                </thead>
                <tbody>
                  {(meta?.classes ?? []).map((c) => (
                    <tr key={c.id}>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <span className="row" style={{ gap: 7 }}>
                          <span className="code" style={{ color: c.color }}>
                            {c.code}
                          </span>
                          {c.label}
                        </span>
                      </td>
                      <td className="dim">{c.description}</td>
                      <td>
                        {c.trained ? (
                          <span className="pri pri-low">trained</span>
                        ) : (
                          <span className="pri pri-medium">abstention</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Module>

          <div style={{ marginTop: 12 }}>
            <Note kind="info">
              <strong>The two industrial classes are separated by time, not by heat.</strong> Both
              sit on the same plant. What distinguishes routine flaring from an incident is
              whether the pixel burns on most days or only this once — which is why detection
              history is a first-class input rather than an afterthought.
            </Note>
          </div>
        </Group>

        {/* ── confidence and abstention ──────────────────────────────── */}
        <Group title="RF vote score and abstention">
          <div className="g2">
            <Module title="Vote-score bands">
              <dl className="kv">
                <dt>High</dt>
                <dd className="num">≥ {pct(thresholds.high)}</dd>
                <dt>Medium</dt>
                <dd className="num">
                  {pct(thresholds.medium)} – {pct(thresholds.high)}
                </dd>
                <dt>Low</dt>
                <dd className="num">&lt; {pct(thresholds.medium)}</dd>
              </dl>
              <p className="sm dim" style={{ marginTop: 10 }}>
                These are prototype defaults, configurable, and not validated against outcomes.
                The RF vote score is a vote share across trees — it is not a calibrated
                real-world likelihood.
              </p>
            </Module>

            <Module title="Abstention, and the evidence gate">
              <p className="sm">
                Below <span className="m">{pct(thresholds.abstention)}</span> the system reports{' '}
                <strong>unclassified</strong> rather than asserting the weak leader. Unclassified
                is not a trained class; it is a refusal.
              </p>
              <p className="sm">
                That bar <strong>rises to{' '}
                <span className="m">{pct(data?.abstention?.low_evidence_threshold)}</span></strong>{' '}
                when the discriminating evidence was unavailable — no mapped facility within the
                search radius <em>and</em> no land-use polygon covering the point.
              </p>
              <p className="sm dim">
                This was added after measuring the ungated model on a live India-wide query in
                September, outside any crop-residue burning season: it returned 810 of 900
                detections as agricultural burning at a median RF vote score of 0.66, and 800 of
                those had no land cover at all. The model had learned that absence of evidence
                resembles cropland. Detection history deliberately does <em>not</em> satisfy the
                gate — it separates a persistent source from a one-off, but says nothing about
                whether the ground below is a wheat field or a forest.
              </p>
            </Module>
          </div>
        </Group>

        {/* ── priority formula ───────────────────────────────────────── */}
        <Group title="Priority score" note={priority.type}>
          <Module>
            <p className="sm" style={{ marginBottom: 14 }}>
              A weighted sum, not a second model. Every component is a named 0–1 number and the
              API returns all of them alongside the score, so a user can see how it was reached
              and disagree with it.
            </p>

            <div className="gridwrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Component</th>
                    <th className="r">Weight</th>
                    <th>Definition</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(priority.components ?? {}).map(([key, description]) => (
                    <tr key={key}>
                      <td style={{ textTransform: 'capitalize', whiteSpace: 'nowrap' }}>
                        {key.replace(/_/g, ' ')}
                      </td>
                      <td className="num">{num(priority.weights?.[key], 2)}</td>
                      <td className="dim">{description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: 14 }}>
              <Note kind="info">
                <strong>Persistence lowers priority.</strong> A flare stack that burns every single
                day is routine and belongs at the bottom of a queue; a strong detection at a plant
                that has never lit up before is exactly what an emergency team wants at the top.
                That inversion is the difference between a fire-detection feed and a triage tool.
              </Note>
            </div>

            <p className="sm dim" style={{ marginTop: 12 }}>
              {priority.caveat}
            </p>
          </Module>
        </Group>

        {/* ── honest limits ──────────────────────────────────────────── */}
        <Group title="Limits of this system">
          <Module>
            <ol className="sm" style={{ paddingLeft: 18, lineHeight: 1.75, margin: 0 }}>
              <li>
                <strong>Satellite hotspots are not ground truth.</strong> FIRMS reports a thermal
                anomaly, not a confirmed fire, and not its cause.
              </li>
              <li>
                <strong>Training labels are inferred, not verified.</strong> They come from the
                documented rule policy (v{policy.version}), so model metrics measure agreement
                with that policy. <Link to="/model">Full detail →</Link>
              </li>
              <li>
                <strong>Thermal signatures genuinely overlap.</strong> A hot crop fire and a small
                industrial fire can look nearly identical to a 375 m sensor. This is the core
                difficulty of the problem, and abstention exists because of it.
              </li>
              <li>
                <strong>OpenStreetMap coverage is uneven and measurably so.</strong> In central
                Punjab 98% of detections fall in no land-use polygon. A missing factory can turn a
                real industrial fire into a different class. <Link to="/data">Coverage figures →</Link>
              </li>
              <li>
                <strong>Industrial fire is the weakest class</strong>, with the fewest labelled
                examples and the lowest recall. Treat those calls as candidates for review.
              </li>
              <li>
                <strong>Absence of a detection is not absence of fire.</strong> Cloud, overpass
                timing and swath geometry all cause misses.
              </li>
              <li>
                <strong>Recurrence needs history.</strong> On a cold start the temporal features
                are weak, and the system reports that history is unavailable rather than treating
                a count of zero as evidence.
              </li>
              <li>
                <strong>This is a prototype</strong>, not a certified operational system. Every
                prediction requires human verification.
              </li>
            </ol>
          </Module>
        </Group>

        {/* ── resilience ─────────────────────────────────────────────── */}
        <Group title="Behaviour when a source fails">
          <Module flush>
            <div className="gridwrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Failure</th>
                    <th>What the system does</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['NASA key absent', 'Historical snapshot, with the reason shown in the banner'],
                    ['FIRMS unreachable or rate-limited', 'Automatic fallback to the snapshot; status pill changes to Historical'],
                    ['One FIRMS product fails', 'Remaining products still used; the response says which were unavailable'],
                    ['Overpass mirror down', 'Fails over to the next mirror, then disk cache, then stored facilities'],
                    ['Land-use unreachable', 'Land cover reported as unknown — never guessed'],
                    ['Model artifact missing', 'Every detection reported unclassified; the interface keeps working'],
                    ['Request exceeds time budget', 'Remaining map tiles served from cache; the response still arrives'],
                  ].map(([failure, behaviour]) => (
                    <tr key={failure}>
                      <td className="nw">{failure}</td>
                      <td className="dim">{behaviour}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Module>
          <div style={{ marginTop: 12 }}>
            <Note kind="plain">
              No failure path substitutes generated data. A failed request produces a visible
              error with a retry, and a missing value stays missing.
            </Note>
          </div>
        </Group>
      </div>
    </div>
  )
}
