import { coords, int, km, num, pct, utcAndIst } from '../lib/format.js'
import { EmptyState, Note, Provenance, Spinner } from './ui.jsx'

function confColour(level) {
  if (level === 'HIGH') return 'var(--ok)'
  if (level === 'MEDIUM') return 'var(--warn)'
  return 'var(--alarm)'
}

function Section({ title, note, children }) {
  return (
    <section className="dock-sec">
      <header className="dock-head">
        <span>{title}</span>
        {note && <span className="faint" style={{ letterSpacing: 0, textTransform: 'none' }}>{note}</span>}
      </header>
      <div className="dock-body">{children}</div>
    </section>
  )
}

/**
 * Per-prediction factors, from decomposing the forest's decision paths for
 * THIS sample — not global feature importance. Wording stays "moved the
 * model's output", never "caused the fire".
 */
function Factors({ factors, loading }) {
  if (loading) {
    return (
      <div className="row dim sm">
        <Spinner /> Computing explanation…
      </div>
    )
  }
  if (!factors?.length) return <p className="na sm">No explanation available.</p>

  return (
    <div>
      {factors.map((f, i) => (
        <div className="fac" key={`${f.feature}-${i}`}>
          <span
            className={`fac-i ${f.direction === 'supports' ? 'fac-sup' : f.direction === 'counters' ? 'fac-cou' : 'fac-neu'}`}
            aria-hidden="true"
          >
            {f.direction === 'supports' ? '+' : f.direction === 'counters' ? '−' : '·'}
          </span>
          <span className="grow">
            <span>{f.text}</span>
            {f.importance != null && (
              <span className="bar-t" style={{ height: 3, marginTop: 3 }}>
                <span
                  className="bar-f"
                  style={{
                    width: `${Math.round(f.importance * 100)}%`,
                    background: 'var(--rule-heavy)',
                  }}
                />
              </span>
            )}
          </span>
          <span className="sr">
            {f.direction === 'supports'
              ? 'supports'
              : f.direction === 'counters'
                ? 'counters'
                : 'neutral'}
          </span>
        </div>
      ))}
    </div>
  )
}

function Probabilities({ probabilities, classMap, predicted }) {
  const rows = Object.entries(probabilities ?? {})
    .filter(([id]) => classMap[id])
    .sort((a, b) => b[1] - a[1])
  if (!rows.length) return null

  return (
    <div>
      {rows.map(([id, p]) => {
        const cls = classMap[id]
        return (
          <div className="bar" key={id}>
            <span className="bar-k" style={{ width: 118 }}>
              <span className="code" style={{ color: cls.color }}>
                {cls.code}
              </span>
              <span
                className="trunc xs"
                style={{
                  color: id === predicted ? 'var(--ink)' : undefined,
                  fontWeight: id === predicted ? 600 : undefined,
                }}
              >
                {cls.label}
              </span>
            </span>
            <span className="bar-t">
              <span className="bar-f" style={{ width: `${p * 100}%`, background: cls.color }} />
            </span>
            <span className="bar-v" style={{ width: 38 }}>
              {pct(p)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function PriorityBreakdown({ priority }) {
  return (
    <div>
      <div className="between" style={{ marginBottom: 7 }}>
        <span className="dim xs">Weighted triage score</span>
        <span className="row" style={{ gap: 6 }}>
          <span className={`pri pri-${priority.level.toLowerCase()}`}>{priority.level}</span>
          <span className="m" style={{ fontSize: 14, fontWeight: 650 }}>
            {priority.score.toFixed(2)}
          </span>
        </span>
      </div>
      {Object.entries(priority.components).map(([k, v]) => (
        <div className="bar" key={k}>
          <span className="bar-k xs" style={{ width: 112, textTransform: 'capitalize' }}>
            <span className="trunc">{k.replace(/_/g, ' ')}</span>
            <span className="m faint" style={{ fontSize: 9.5 }}>
              ×{priority.weights[k]?.toFixed(2)}
            </span>
          </span>
          <span className="bar-t" style={{ height: 7 }}>
            <span className="bar-f" style={{ width: `${v * 100}%`, background: 'var(--ink-2)' }} />
          </span>
          <span className="bar-v" style={{ width: 30 }}>
            {v.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function Inspector({ item, classMap, loadingDetail }) {
  if (!item) {
    return (
      <aside className="dock dock-r">
        <header className="dock-head">
          <span>Inspector</span>
        </header>
        <EmptyState title="No detection selected">
          Click a marker on the map, or a row in the grid below it, to see the evidence behind its
          classification.
        </EmptyState>
      </aside>
    )
  }

  const { event, classification, evidence, factors, priority, probabilities, model } = item
  const cls = classMap[classification.label]
  const times = utcAndIst(event.acquired_at)
  const rec = evidence.recurrence
  const lcUnknown = evidence.land_cover.category === 'unknown'

  return (
    <aside className="dock dock-r">
      <header className="dock-head">
        <span>Inspector</span>
        <span className="m faint" style={{ letterSpacing: 0, textTransform: 'none' }}>
          {event.event_id}
        </span>
      </header>

      {/* ── verdict ─────────────────────────────────────────────────── */}
      <div className="insp-verdict">
        <div className="cmd-label" style={{ marginBottom: 4 }}>
          Likely source — model assessment
        </div>
        <div className="insp-class">
          <span className="swatch" style={{ background: cls?.color, width: 11, height: 11 }} />
          {classification.label_display}
        </div>

        <div className="between" style={{ marginTop: 9 }}>
          <span className="dim xs">RF vote score</span>
          <span className="m" style={{ fontWeight: 650 }}>
            {pct(classification.confidence)}
          </span>
        </div>
        <div className="gauge">
          <span
            style={{
              width: `${Math.max(2, classification.confidence * 100)}%`,
              background: confColour(classification.confidence_level),
            }}
          />
        </div>
        <p className="xs faint" style={{ marginTop: 5 }}>
          {classification.abstained
            ? `Abstained — strongest trained class was ${classification.top_trained_label}.`
            : `${classification.confidence_level} vote-score band (not a calibrated probability).`}
        </p>

        {classification.abstained && (
          <div style={{ marginTop: 8 }}>
            <Note kind="warn">{classification.description}</Note>
          </div>
        )}
      </div>

      <Section title="Factors" note="this detection">
        <Factors factors={factors} loading={loadingDetail} />
        <Provenance note="Computed per detection by decomposing each tree's decision path. These are the factors that moved this output — not the model's general importance, and not a causal account of the fire." />
      </Section>

      <Section title="Class probabilities">
        <Probabilities
          probabilities={probabilities}
          classMap={classMap}
          predicted={classification.top_trained_label}
        />
      </Section>

      <Section title="Evidence">
        <dl className="kv">
          <dt>Facility</dt>
          <dd>
            {evidence.nearest_facility ? (
              <>
                {evidence.nearest_facility.name || evidence.nearest_facility.category_label}
                <div className="faint xs">{evidence.nearest_facility.category_label}</div>
              </>
            ) : (
              <span className="na">none mapped in radius</span>
            )}
          </dd>

          <dt>Distance</dt>
          <dd className="m">{km(evidence.distance_to_nearest_facility_km)}</dd>

          <dt>Land cover</dt>
          <dd>
            {lcUnknown ? (
              <span className="na">not mapped in OSM</span>
            ) : (
              <>
                {evidence.land_cover.label}
                <div className="faint xs">
                  {evidence.land_cover.matched_osm_tag ?? evidence.land_cover.provider}
                </div>
              </>
            )}
          </dd>

          <dt>Recurrence</dt>
          <dd>
            {rec.history_available ? (
              <>
                <span className="m">{int(rec.distinct_days)}</span> day
                {rec.distinct_days === 1 ? '' : 's'} / {rec.window_days}d
                <div className="faint xs">
                  {int(rec.recurrence_count)} prior within {rec.radius_km} km
                  {rec.is_persistent && ' · persistent'}
                </div>
              </>
            ) : (
              <span className="na">no history loaded</span>
            )}
          </dd>

          <dt>Co-detected</dt>
          <dd className="m">{int(rec.nearby_density)} same pass</dd>

          <dt>FRP</dt>
          <dd className="m">
            {evidence.frp_mw === null ? <span className="na">not reported</span> : `${num(evidence.frp_mw)} MW`}
          </dd>

          <dt>Brightness</dt>
          <dd className="m">
            {evidence.thermal_intensity_k === null ? (
              <span className="na">not reported</span>
            ) : (
              `${num(evidence.thermal_intensity_k, 1)} K`
            )}
          </dd>

          <dt>FIRMS conf.</dt>
          <dd>{evidence.firms_confidence ?? <span className="na">not reported</span>}</dd>
        </dl>
      </Section>

      <Section title="Priority">
        <PriorityBreakdown priority={priority} />
      </Section>

      <Section title="Observation record">
        <dl className="kv">
          <dt>Position</dt>
          <dd className="m">{coords(event.latitude, event.longitude)}</dd>
          <dt>Acquired</dt>
          <dd className="m">
            {times.ist}
            <div className="faint xs">{times.utc}</div>
          </dd>
          <dt>Platform</dt>
          <dd>
            {event.satellite ?? '—'} {event.instrument ? `· ${event.instrument}` : ''}
            <div className="faint xs">{event.day_night === 'N' ? 'Night pass' : 'Day pass'}</div>
          </dd>
          <dt>Product</dt>
          <dd className="m xs">{event.source_product}</dd>
          <dt>Mode</dt>
          <dd>
            <span className={event.source_mode === 'live' ? 'chip chip-live' : 'chip chip-hist'}>
              <span className="led" />
              {event.source_mode === 'live' ? 'Live' : 'Historical'}
            </span>
          </dd>
          <dt>Model</dt>
          <dd className="m xs">RF v{model.model_version}</dd>
        </dl>

        {event.unavailable_fields?.length > 0 && (
          <div style={{ marginTop: 9 }}>
            <Note kind="plain" icon={false}>
              Not supplied by this product:{' '}
              <span className="m">{event.unavailable_fields.join(', ')}</span>. Left empty rather
              than filled with a substitute.
            </Note>
          </div>
        )}
      </Section>

      <div className="dock-body">
        <p className="xs faint">{item.disclaimer}</p>
      </div>
    </aside>
  )
}
