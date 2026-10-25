import { useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  IconCheck,
  IconCheckCircle,
  IconClose,
  IconDot,
  IconFlame,
  IconMinus,
  IconRefresh,
  IconSearch,
  IconWarn,
} from './mapicons.jsx'

/* Every panel on the main screen. Each one is passive: it renders fields the
 * backend supplied and reports clicks upward. No panel composes a sentence of
 * its own, so nothing on screen can say something the API did not. */

// ---------------------------------------------------------------- helpers
const STATUS_CSS = {
  needs_attention: 'var(--m-attn)',
  watch: 'var(--m-watch)',
  normal: 'var(--m-normal)',
  not_sure: 'var(--m-unsure)',
}

/** "12 min ago" / "3 h ago" / "11 Nov 2025". Absolute once it is not today. */
export function ago(iso) {
  if (!iso) return null
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return null
  const mins = Math.floor((Date.now() - then.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} h ago`
  return then.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

function absolute(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  }) + ' UTC'
}

// ------------------------------------------------------------- brand card
/**
 * Top-left. Four elements, no more: the name, one summary line, the provenance
 * chip, and the observation age.
 */
export function BrandCard({ counts, provenance, observedTo, loading, mode, onMode, busy }) {
  const chip = provenanceChip(provenance)

  return (
    <div className="m-panel m-brandcard">
      <div className="m-brand">
        <span className="m-brand-mark">
          <IconFlame width={18} height={18} />
        </span>
        <span className="m-brand-name">FIRETRACE</span>
      </div>

      {loading && !counts ? (
        <div style={{ marginBottom: 'var(--m-s3)' }}>
          <div className="m-skel m-skel-line" style={{ width: '88%' }} />
          <div className="m-skel m-skel-line" style={{ width: '54%', marginBottom: 0 }} />
        </div>
      ) : (
        <p className="m-summary">
          {counts && counts.needs_attention + counts.watch + counts.not_sure + counts.normal > 0 ? (
            <>
              <b>{counts.needs_attention}</b> need attention
              <span className="m-dot"> · </span>
              <b>{counts.watch}</b> watch
              <span className="m-dot"> · </span>
              <b>{counts.normal}</b> normal
            </>
          ) : (
            'No thermal detections in this window.'
          )}
        </p>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--m-s2)', flexWrap: 'wrap' }}>
        <span className={`m-chip ${chip.className}`} title={provenance?.detail ?? ''}>
          <span className="m-chip-led" />
          {chip.label}
        </span>

        {/* Switching source is a two-state control, not a hidden setting: the
            demo has to be able to leave a dead venue network in one click. */}
        {onMode && (
          <button
            className="m-ghost"
            style={{ position: 'static', height: 28, boxShadow: 'none', padding: '0 10px' }}
            onClick={() => onMode(mode === 'demo' ? 'auto' : 'demo')}
            disabled={busy}
            title={
              mode === 'demo'
                ? 'Try the live NASA FIRMS feed'
                : 'Switch to the offline historical archive'
            }
          >
            {mode === 'demo' ? 'Try live' : 'Use archive'}
          </button>
        )}
      </div>

      {observedTo && (
        <div className="m-age">
          Satellite observation {ago(observedTo)}
          {provenance?.retrieved_at ? ` · checked ${ago(provenance.retrieved_at)}` : ''}
        </div>
      )}
    </div>
  )
}

/**
 * The provenance chip is the single most important honesty surface on the
 * screen, so its five states are explicit and never computed from a truthy
 * check. A replay must not be able to look like live data.
 */
export function provenanceChip(p) {
  switch (p?.state) {
    case 'live':
      return { className: 'm-chip-live', label: 'Live · NASA FIRMS' }
    case 'live_empty':
      return { className: 'm-chip-empty', label: 'Live · no detections in window' }
    case 'offline':
      return { className: 'm-chip-offline', label: 'Offline · showing saved data' }
    case 'replay':
      return { className: 'm-chip-replay', label: 'Replay · real historical data' }
    case 'simulated':
      return { className: 'm-chip-offline', label: 'Simulated scenario' }
    case 'unavailable':
      return { className: 'm-chip-down', label: 'Live feed unavailable' }
    default:
      return { className: 'm-chip-empty', label: 'Connecting…' }
  }
}

// ----------------------------------------------------------------- search
export function SearchBar({ value, onChange, results, onPick, busy, loading }) {
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(-1)
  const wrapRef = useRef(null)
  const listId = useId()

  useEffect(() => {
    const away = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  useEffect(() => setCursor(-1), [results])

  const show = open && value.trim().length >= 2
  const items = results ?? []

  const onKeyDown = (e) => {
    if (!show) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor((c) => Math.min(c + 1, items.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    } else if (e.key === 'Enter' && cursor >= 0 && items[cursor]) {
      e.preventDefault()
      onPick(items[cursor])
      setOpen(false)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div style={{ position: 'relative' }} ref={wrapRef}>
      <div className="m-search">
        <IconSearch />
        {/* role="combobox" is required for aria-expanded/aria-controls to be
            legal here: axe-core flags them as unsupported on a bare searchbox
            (rule aria-allowed-attr, critical). With the role set, the input and
            its results list form a proper combobox pattern. */}
        <input
          type="search"
          role="combobox"
          value={value}
          placeholder="Search a facility or company"
          aria-label="Search a mapped industrial facility or company"
          aria-expanded={show}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          onChange={(e) => {
            onChange(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {value && (
          <button className="m-search-clear" onClick={() => onChange('')} aria-label="Clear search">
            <IconClose width={14} height={14} />
          </button>
        )}
      </div>

      {show && (
        <div className="m-results" id={listId} role="listbox">
          {busy && !items.length ? (
            <div className="m-empty-note">Searching…</div>
          ) : items.length ? (
            items.map((r, i) => (
              <button
                key={`${r.kind}-${r.id}`}
                className="m-result"
                role="option"
                aria-selected={i === cursor}
                onClick={() => {
                  onPick(r)
                  setOpen(false)
                }}
              >
                <span
                  className="m-filter-swatch"
                  style={{ background: r.status ? STATUS_CSS[r.status] : 'var(--m-border-strong)' }}
                />
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span className="m-result-name" style={{ display: 'block' }}>
                    {r.name}
                  </span>
                  <span className="m-result-detail">{r.detail}</span>
                </span>
              </button>
            ))
          ) : (
            <div className="m-empty-note">
              {loading
                ? 'Loading detections…'
                : 'No mapped facility matches. This searches OpenStreetMap facility names, not place names.'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- filters
export function FilterChips({ active, onToggle, windowDays, onWindow, counts }) {
  const chips = [
    { key: 'needs_attention', label: 'Needs attention' },
    { key: 'watch', label: 'Watch' },
    { key: 'not_sure', label: `Not sure${counts?.not_sure ? ` ${counts.not_sure}` : ''}` },
  ]

  return (
    <div className="m-filters">
      {chips.map((c) => (
        <button
          key={c.key}
          className="m-filter"
          aria-pressed={active.includes(c.key)}
          onClick={() => onToggle(c.key)}
        >
          <span className="m-filter-swatch" style={{ background: STATUS_CSS[c.key] }} />
          {c.label}
        </button>
      ))}
      <button
        className="m-filter"
        aria-pressed={windowDays > 1}
        onClick={() => onWindow(windowDays > 1 ? 1 : 3)}
        title="Switch the observation window"
      >
        {windowDays > 1 ? 'Last 3 days' : 'Last 24 h'}
      </button>
    </div>
  )
}

// -------------------------------------------------------------- site card
/**
 * The content budget here is the whole point: a status chip, one verdict
 * sentence, at most three why-lines, one small chart and the uncertainty note.
 * Everything quantitative is one click away in the evidence drawer.
 */
export function SiteCard({ site, onClose, onEvidence, onReview, reviewed }) {
  if (!site) return null

  return (
    <div
      className="m-panel m-sitecard"
      role="dialog"
      aria-label={`${site.status_label}: ${site.title}`}
    >
      <div className="m-card-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="m-card-title">{site.title}</div>
          <div className="m-card-sub">{site.subtitle}</div>
        </div>
        <button className="m-close" onClick={onClose} aria-label="Close details">
          <IconClose />
        </button>
      </div>

      <div className="m-card-body">
        <span className={`m-status-chip m-status-${site.status}`}>
          <IconDot width={10} height={10} />
          {site.status_label}
        </span>

        <p className="m-verdict">{site.verdict}</p>

        {site.why?.length > 0 && (
          <ul className="m-why">
            {site.why.map((w) => (
              <li key={w}>
                <IconCheck width={13} height={13} />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        )}

        <HeatBand site={site} />

        {site.missing?.length > 0 && (
          <div className="m-unsure-note">
            <b>Not sure about:</b> {site.missing.slice(0, 2).join('. ')}.
          </div>
        )}
      </div>

      <div className="m-actions">
        <button className="m-btn" onClick={onEvidence}>
          See evidence
        </button>
        <button className="m-btn m-btn-primary" onClick={onReview} disabled={reviewed}>
          {reviewed ? (
            <>
              <IconCheckCircle width={14} height={14} />
              Reviewed
            </>
          ) : (
            'Mark reviewed'
          )}
        </button>
      </div>
    </div>
  )
}

/**
 * The one small chart: this detection's peak radiative power against the range
 * recorded at this location.
 *
 * When there is no usable history the band is not drawn at all. An invented
 * "normal" band would be the single most misleading pixel on the screen, so
 * the honest version of this chart is sometimes no chart.
 */
function HeatBand({ site }) {
  const frp = site.frp_max_mw
  if (frp === null || frp === undefined) {
    return (
      <div className="m-band">
        <div className="m-band-label">Heat output</div>
        <div className="m-band-note">Radiative power was not reported for this detection.</div>
      </div>
    )
  }

  const hasBaseline = site.history_available && site.distinct_days > 0
  // A fixed reference scale, labelled as such — not a per-facility baseline.
  const scaleMax = Math.max(frp * 1.25, 40)
  const pct = Math.min(100, (frp / scaleMax) * 100)

  return (
    <div className="m-band">
      <div className="m-band-label">Heat output</div>
      <div
        style={{
          position: 'relative',
          height: 26,
          background: 'var(--m-surface-sunk)',
          borderRadius: 6,
          border: '1px solid var(--m-border)',
        }}
        role="img"
        aria-label={`Peak radiative power ${frp.toFixed(1)} megawatts`}
      >
        <div
          style={{
            position: 'absolute',
            left: `calc(${pct}% - 2px)`,
            top: 3,
            bottom: 3,
            width: 4,
            borderRadius: 2,
            background: STATUS_CSS[site.status],
          }}
        />
      </div>
      <div className="m-band-note">
        Peak {frp.toFixed(1)} MW on a 0–{Math.round(scaleMax)} MW scale.{' '}
        {hasBaseline
          ? `This location was detected on ${site.distinct_days} earlier ${
              site.distinct_days === 1 ? 'day' : 'days'
            } in the history window.`
          : 'No usable history at this location, so no normal range is drawn.'}
      </div>
    </div>
  )
}

// --------------------------------------------------------- attention list
export function AttentionList({ sites, onPick, selectedId }) {
  const top = useMemo(() => sites.slice(0, 5), [sites])
  if (!top.length) return null

  return (
    <div className="m-panel m-attnlist">
      <div className="m-attnlist-head">
        <span>Needs attention first</span>
      </div>
      {top.map((s) => (
        <button
          key={s.id}
          className="m-attnrow"
          onClick={() => onPick(s.id)}
          aria-current={s.id === selectedId ? 'true' : undefined}
        >
          <span className="m-attnrow-swatch" style={{ background: STATUS_CSS[s.status] }} />
          <span className="m-attnrow-name">{s.title}</span>
        </button>
      ))}
    </div>
  )
}

// -------------------------------------------------------- evidence drawer
/**
 * Secondary by design. Grouped Heat / Place / History / Context, each item
 * marked supporting, missing or contradicting, with the numbers folded away
 * under "Details for experts".
 */
export function EvidenceDrawer({ site, provenance, model, disclaimer, onClose }) {
  const closeRef = useRef(null)

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!site) return null

  const missing = new Set(site.missing ?? [])
  const groups = buildEvidenceGroups(site, missing)

  return (
    <>
      <div className="m-drawer-scrim" onClick={onClose} />
      <div className="m-drawer" role="dialog" aria-modal="true" aria-label="Evidence">
        <div className="m-drawer-head">
          <span className="m-drawer-title">Evidence</span>
          <button className="m-close" ref={closeRef} onClick={onClose} aria-label="Close evidence">
            <IconClose />
          </button>
        </div>

        <div className="m-drawer-body">
          <p style={{ fontSize: 'var(--m-t-xs)', color: 'var(--m-ink-2)', margin: '0 0 var(--m-s4)', lineHeight: 1.5 }}>
            {site.title} · {site.status_label}
          </p>

          {groups.map((g) => (
            <section className="m-group" key={g.title}>
              <h3 className="m-group-title">{g.title}</h3>
              {g.items.map((item) => (
                <div className={`m-ev m-ev-${item.kind}`} key={item.text}>
                  {item.kind === 'supporting' ? (
                    <IconCheck width={14} height={14} />
                  ) : item.kind === 'contradicting' ? (
                    <IconMinus width={14} height={14} />
                  ) : (
                    <IconWarn width={14} height={14} />
                  )}
                  <span>{item.text}</span>
                </div>
              ))}
            </section>
          ))}

          <section className="m-group">
            <h3 className="m-group-title">What this is not</h3>
            <p style={{ fontSize: 'var(--m-t-xs)', color: 'var(--m-ink-2)', lineHeight: 1.5, margin: 0 }}>
              Proximity to a facility is context, not proof of cause. A detection on a
              site does not establish that the site caused it. {disclaimer}
            </p>
          </section>

          <details className="m-fold">
            <summary>Details for experts</summary>
            <div className="m-fold-body">
              <dl className="m-kv">
                <dt>Predicted class</dt>
                <dd>{site.predicted_class_display}</dd>

                <dt>Model score</dt>
                <dd>
                  {site.model_score?.toFixed(3) ?? '—'}
                  {site.abstained ? ' (abstained)' : ''}
                </dd>

                <dt>Operational priority</dt>
                <dd>
                  {site.operational_priority} · {site.priority_score?.toFixed(3)}
                </dd>

                <dt>Evidence completeness</dt>
                <dd>
                  {site.evidence_completeness?.available}/{site.evidence_completeness?.total} checks
                </dd>

                <dt>Detections in group</dt>
                <dd>{site.detection_count}</dd>

                <dt>Distinct passes</dt>
                <dd>{site.distinct_passes}</dd>

                <dt>Prior days seen</dt>
                <dd>{site.history_available ? site.distinct_days : 'no history loaded'}</dd>

                <dt>Peak / total FRP</dt>
                <dd>
                  {site.frp_max_mw ?? '—'} / {site.frp_total_mw ?? '—'} MW
                </dd>

                <dt>Peak brightness</dt>
                <dd>{site.brightness_max_k ? `${site.brightness_max_k} K` : '—'}</dd>

                <dt>Land cover</dt>
                <dd>{site.land_cover}</dd>

                <dt>Observed at</dt>
                <dd>{absolute(site.observed_at)}</dd>

                <dt>Retrieved at</dt>
                <dd>{absolute(provenance?.retrieved_at)}</dd>

                <dt>Source</dt>
                <dd>{(site.products ?? []).join(', ') || provenance?.source}</dd>

                <dt>Provenance</dt>
                <dd>{provenanceChip(provenance).label}</dd>

                <dt>Model version</dt>
                <dd>
                  {model?.model_version} · {model?.n_features}f
                </dd>
              </dl>

              <p style={{ fontSize: 11, color: 'var(--m-ink-3)', marginTop: 'var(--m-s3)', marginBottom: 0, lineHeight: 1.5 }}>
                {model?.score_note}
              </p>
            </div>
          </details>
        </div>
      </div>
    </>
  )
}

/**
 * Sorts the event's own fields into the four evidence groups.
 *
 * `missing` lines come from the backend's missing_evidence(); they are never
 * folded in as supporting evidence. An unmapped land-cover polygon is an
 * absence, and the previous factor generator marked some of these as
 * "supports", which is the specific mistake this separation prevents.
 */
function buildEvidenceGroups(site, missing) {
  const heat = []
  if (site.frp_max_mw != null)
    heat.push({ kind: 'supporting', text: `Peak radiative power ${site.frp_max_mw} MW` })
  if (site.frp_total_mw != null && site.detection_count > 1)
    heat.push({ kind: 'supporting', text: `Combined radiative power ${site.frp_total_mw} MW` })
  if (site.brightness_max_k != null)
    heat.push({ kind: 'supporting', text: `Peak brightness temperature ${site.brightness_max_k} K` })
  if (!heat.length) heat.push({ kind: 'missing', text: 'No thermal magnitude was reported' })

  const place = []
  if (site.nearest_facility_km != null) {
    place.push({
      kind: 'supporting',
      text:
        site.nearest_facility_km <= 0.75
          ? `On the footprint of ${site.nearest_facility_name} (${Math.round(site.nearest_facility_km * 1000)} m)`
          : `${site.nearest_facility_km.toFixed(2)} km from ${site.nearest_facility_name}`,
    })
  } else {
    place.push({ kind: 'missing', text: 'No mapped industrial facility within the search radius' })
  }
  if (site.land_cover && !/unknown|not mapped/i.test(site.land_cover)) {
    place.push({ kind: 'supporting', text: `Land cover: ${site.land_cover}` })
  } else {
    place.push({ kind: 'missing', text: 'Land cover is not mapped here in OpenStreetMap' })
  }

  const history = []
  if (!site.history_available) {
    history.push({ kind: 'missing', text: 'No detection history is loaded for this location' })
  } else if (site.distinct_days > 0) {
    history.push({
      kind: site.persistent ? 'contradicting' : 'supporting',
      text: site.persistent
        ? `Recurring source — detected on ${site.distinct_days} separate days, which counts against an incident reading`
        : `Detected on ${site.distinct_days} earlier ${site.distinct_days === 1 ? 'day' : 'days'} in the history window`,
    })
  } else {
    history.push({ kind: 'supporting', text: 'No earlier detection at this location in the window' })
  }
  history.push({
    kind: site.distinct_passes > 1 ? 'supporting' : 'missing',
    text:
      site.distinct_passes > 1
        ? `Confirmed across ${site.distinct_passes} separate satellite passes`
        : 'Only one satellite pass so far — not yet corroborated',
  })

  const context = [{ kind: 'missing', text: 'Optical confirmation: not available' }]
  for (const m of missing) {
    if (/optical/i.test(m)) continue
    if (![...heat, ...place, ...history].some((i) => i.text === m)) {
      context.push({ kind: 'missing', text: m })
    }
  }

  return [
    { title: 'Heat', items: heat },
    { title: 'Place', items: place },
    { title: 'History', items: history },
    { title: 'Context', items: context },
  ]
}

// --------------------------------------------------------------- banner
export function FallbackBanner({ provenance, onRetry, busy }) {
  if (!provenance) return null
  if (provenance.state !== 'offline' && provenance.state !== 'unavailable') return null

  return (
    <div className="m-banner" role="status">
      <span style={{ flex: 1 }}>
        {provenance.state === 'offline'
          ? `Live feed unavailable — showing saved data. ${provenance.detail ?? ''}`
          : `Live feed unavailable. ${provenance.detail ?? ''}`}
      </span>
      <button className="m-banner-retry" onClick={onRetry} disabled={busy}>
        <IconRefresh width={12} height={12} style={{ verticalAlign: '-2px', marginRight: 4 }} />
        {busy ? 'Retrying…' : 'Retry'}
      </button>
    </div>
  )
}
