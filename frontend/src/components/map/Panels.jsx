import { useEffect, useId, useRef, useState } from 'react'
import { IconCheck, IconClose, IconMinus, IconSearch, IconWarn } from './mapicons.jsx'

/* Search, filter chips and the evidence drawer.
 *
 * Every panel is passive: it renders fields the backend supplied and reports
 * clicks upward. No panel composes a sentence of its own, so nothing on screen
 * can say something the API did not.
 */

const STATUS_VAR = {
  needs_attention: 'var(--s-attn)',
  watch: 'var(--s-watch)',
  normal: 'var(--s-normal)',
  not_sure: 'var(--s-unsure)',
}

function absolute(iso) {
  if (!iso) return '—'
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return '—'
  return (
    when.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'Asia/Kolkata',
    }) + ' IST'
  )
}

// ----------------------------------------------------------------- search
export function SearchBar({ value, onChange, results, onPick, busy, loading }) {
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(-1)
  const wrapRef = useRef(null)
  const listId = useId()

  useEffect(() => {
    const away = (event) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  useEffect(() => setCursor(-1), [results])

  const show = open && value.trim().length >= 2
  const items = results ?? []

  const onKeyDown = (event) => {
    if (!show) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((c) => Math.min(c + 1, items.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    } else if (event.key === 'Enter' && cursor >= 0 && items[cursor]) {
      event.preventDefault()
      onPick(items[cursor])
      setOpen(false)
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div style={{ position: 'relative' }} ref={wrapRef}>
      <div className="fc-search">
        <IconSearch width={16} height={16} />
        {/* The full ARIA 1.2 combobox pattern, not just aria-expanded.
            axe flagged aria-expanded on a bare search input as a critical
            aria-allowed-attr violation: the attribute is only meaningful once
            the element actually claims to be a combobox, and a screen reader
            has no way to announce the suggestion list without the role,
            aria-autocomplete and aria-activedescendant. */}
        <input
          type="search"
          role="combobox"
          value={value}
          placeholder="Search a facility or company"
          aria-label="Search a mapped industrial facility or company"
          aria-expanded={show}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            show && cursor >= 0 && items[cursor] ? `${listId}-opt-${cursor}` : undefined
          }
          autoComplete="off"
          onChange={(event) => {
            onChange(event.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {value ? (
          <button
            type="button"
            className="fc-iconbtn fc-iconbtn-sm"
            onClick={() => onChange('')}
            aria-label="Clear search"
          >
            <IconClose width={14} height={14} />
          </button>
        ) : (
          /* A quiet hint that the palette exists, rather than a tour. */
          <span className="fc-kbdhint" aria-hidden="true">
            <kbd>Ctrl</kbd>
            <kbd>K</kbd>
          </span>
        )}
      </div>

      {show && (
        <div className="fc-results" id={listId} role="listbox">
          {busy && !items.length ? (
            <p className="fc-pop-empty">Searching…</p>
          ) : items.length ? (
            items.map((hit, index) => (
              <button
                key={`${hit.kind}-${hit.id}`}
                id={`${listId}-opt-${index}`}
                type="button"
                className="fc-result"
                role="option"
                aria-selected={index === cursor}
                onClick={() => {
                  onPick(hit)
                  setOpen(false)
                }}
              >
                <span
                  className="fc-swatch"
                  style={{
                    background: hit.status ? STATUS_VAR[hit.status] : 'var(--border-strong)',
                  }}
                />
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span className="fc-result-name">{hit.name}</span>
                  <span className="fc-result-detail">{hit.detail}</span>
                </span>
              </button>
            ))
          ) : (
            <p className="fc-pop-empty">
              {loading
                ? 'Loading detections…'
                : 'No mapped facility matches. This searches OpenStreetMap facility names, not place names.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- filters
export function FilterChips({ active, onToggle, counts }) {
  // Counts are shown on every chip or none, so the row cannot look like some
  // numbers are missing. A zero is information.
  const chips = [
    { key: 'needs_attention', label: 'Needs attention' },
    { key: 'watch', label: 'Watch' },
    { key: 'not_sure', label: 'Not sure' },
  ]
  const haveCounts = counts && typeof counts.needs_attention === 'number'

  return (
    <div className="fc-filters">
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          className="fc-chip"
          aria-pressed={active.includes(chip.key)}
          onClick={() => onToggle(chip.key)}
        >
          <span className="fc-swatch" style={{ background: STATUS_VAR[chip.key] }} />
          {chip.label}
          {haveCounts ? ` ${counts[chip.key] ?? 0}` : ''}
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
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!site) return null

  const groups = buildEvidenceGroups(site, new Set(site.missing ?? []))

  return (
    <>
      <div className="fc-scrim" onClick={onClose} />
      <div className="fc-drawer" role="dialog" aria-modal="true" aria-label="Evidence">
        <header className="fc-drawer-head">
          <span className="fc-drawer-title">Evidence</span>
          <button
            type="button"
            className="fc-iconbtn fc-iconbtn-sm"
            ref={closeRef}
            onClick={onClose}
            aria-label="Close evidence"
          >
            <IconClose width={15} height={15} />
          </button>
        </header>

        <div className="fc-drawer-body">
          <p style={{ fontSize: 'var(--t-12)', color: 'var(--ink-2)', margin: '0 0 var(--sp-4)', lineHeight: 1.5 }}>
            {site.title} · {site.status_label}
          </p>

          {groups.map((group) => (
            <section className="fc-group" key={group.title}>
              <h3 className="fc-group-title">{group.title}</h3>
              {group.items.map((item) => (
                <div className={`fc-ev fc-ev-${item.kind}`} key={item.text}>
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

          <section className="fc-group">
            <h3 className="fc-group-title">What this is not</h3>
            <p style={{ fontSize: 'var(--t-12)', color: 'var(--ink-2)', lineHeight: 1.55, margin: 0 }}>
              Proximity to a facility is context, not proof of cause. A detection on a
              site does not establish that the site caused it. {disclaimer}
            </p>
          </section>

          <details className="fc-fold">
            <summary>Details for experts</summary>
            <div className="fc-fold-body">
              <dl className="fc-kv">
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

                <dt>Abnormality for this site</dt>
                <dd>
                  {site.abnormality_score === null || site.abnormality_score === undefined
                    ? 'not assessed — too little history here'
                    : `${site.abnormality_score}/100`}
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
                <dd>{absolute(provenance?.feed?.retrieved_at ?? provenance?.retrieved_at)}</dd>

                <dt>Source</dt>
                <dd>{(site.products ?? []).join(', ') || provenance?.source}</dd>

                <dt>Data state</dt>
                <dd>{provenance?.surface === 'past' ? 'Past data' : 'Live'}</dd>

                <dt>Model version</dt>
                <dd>
                  {model?.model_version} · {model?.n_features}f
                </dd>
              </dl>

              <p style={{ fontSize: 'var(--t-11)', color: 'var(--ink-3)', marginTop: 'var(--sp-3)', marginBottom: 0, lineHeight: 1.55 }}>
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
 * absence, and the original factor generator marked some of these as
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
    place.push({ kind: 'supporting', text: `Surroundings: ${site.land_cover}` })
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
        ? `Persistent source — detected on ${site.distinct_days} separate days, which counts against an incident reading`
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
  if (site.abnormality_status && site.abnormality_status !== 'assessed') {
    history.push({
      kind: 'missing',
      text: 'Not enough history here to say whether this is unusual for this location',
    })
  }

  const context = [{ kind: 'missing', text: 'Optical check: not available' }]
  for (const line of missing) {
    if (/optical/i.test(line)) continue
    if (![...heat, ...place, ...history].some((item) => item.text === line)) {
      context.push({ kind: 'missing', text: line })
    }
  }

  return [
    { title: 'Heat', items: heat },
    { title: 'Place', items: place },
    { title: 'History', items: history },
    { title: 'Context', items: context },
  ]
}
