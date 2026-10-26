import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { IconChevronDown, IconFlame } from './mapicons.jsx'

/**
 * The top-left control. Product mark, one segmented Live | Past data, and one
 * quiet freshness line. Nothing else is permitted here.
 *
 * Rules this component exists to enforce:
 *
 * 1. **No hard-coded dates.** Every date and age is computed from timestamps the
 *    backend supplied. Pass 1 shipped a chip reading "Satellite observation 11
 *    Sept 2026" that kept saying so regardless of the data underneath.
 * 2. **No "try live", no "demo", no "offline".** A delayed feed is still Live;
 *    the honesty goes in the age, not the label. What is forbidden is the
 *    reverse — stale data that looks fresh — so the age is always rendered and
 *    the dot turns amber.
 * 3. **The age ticks.** A freshness line that was rendered once and never
 *    updated is a lie that gets worse every minute, so it recomputes on a
 *    30-second interval.
 */

const TICK_MS = 30_000

/** "just now" / "4 min ago" / "3 h ago" / "2 days ago". Never a bare date. */
function relativeAge(minutes) {
  if (minutes === null || minutes === undefined) return null
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.floor(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

/** Exact wall-clock in both zones, for the tooltip. */
function exactTimes(iso) {
  if (!iso) return null
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return null
  const fmt = (timeZone, label) =>
    `${when.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone,
    })} ${label}`
  return { ist: fmt('Asia/Kolkata', 'IST'), utc: fmt('UTC', 'UTC') }
}

export default function LiveControl({
  provenance,
  ranges,
  activeRange,
  onSelectLive,
  onSelectRange,
  counts,
  // Which surface the user asked for. Separate from what the payload says, so
  // the control responds to a click without waiting for a fetch.
  requestedPast = false,
}) {
  const [, forceTick] = useState(0)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [tipOpen, setTipOpen] = useState(false)
  const pickerRef = useRef(null)
  const pickerId = useId()
  const tipId = useId()

  // Recompute the age on a timer. The value comes from the backend as a minute
  // count at fetch time, so without this the line silently ages.
  useEffect(() => {
    const timer = setInterval(() => forceTick((n) => n + 1), TICK_MS)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    const away = (event) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target)) setPickerOpen(false)
    }
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setPickerOpen(false)
        setTipOpen(false)
      }
    }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  const isPast = requestedPast
  const feed = provenance?.feed ?? {}
  const state = provenance?.state
  // The payload has not caught up with the requested surface yet.
  const settling = provenance != null && (provenance.surface === 'past') !== requestedPast

  // Minutes elapsed since the backend computed the age, added back on, so the
  // line keeps counting between fetches instead of freezing at its fetch value.
  const drift = useMemo(() => {
    if (!feed.retrieved_at) return 0
    const since = (Date.now() - new Date(feed.retrieved_at).getTime()) / 60000
    return Number.isFinite(since) && since > 0 ? Math.floor(since) : 0
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feed.retrieved_at, Math.floor(Date.now() / TICK_MS)])

  const observedAge =
    feed.observed_age_minutes === null || feed.observed_age_minutes === undefined
      ? null
      : feed.observed_age_minutes + drift

  const tone =
    isPast ? 'past' : state === 'delayed' ? 'warn' : state === 'unavailable' ? 'warn' : 'ok'

  let line
  /* No payload means nothing to describe.
   *
   * This guard used to be `loading && !provenance`, which looked equivalent and
   * was not: switching surface clears the payload a tick before the fetch sets
   * `loading`, so for one render `provenance` was undefined while `isPast` was
   * already true — and the Past branch below dereferenced `provenance.range`
   * and threw, blanking the whole control. The absence of data is the condition;
   * whether a request happens to be in flight is not. */
  if (!provenance || settling) {
    line = null
  } else if (isPast) {
    // The floating replay badge is hidden on narrow screens, so the card itself
    // has to carry the statement. Said here rather than only in the badge.
    line = `Showing ${provenance.range?.label ?? activeRange?.label ?? 'a saved period'} — no alerts are sent`
  } else if (state === 'empty') {
    line = 'No new detections in the last 24 h'
  } else if (state === 'unavailable') {
    line = 'Waiting for the first update.'
  } else if (state === 'delayed') {
    line = `Feed delayed · last update ${relativeAge(observedAge) ?? 'unknown'}`
  } else {
    line = `Updated ${relativeAge(observedAge) ?? 'just now'}`
  }

  const exact = exactTimes(feed.observed_at)
  const retrieved = exactTimes(feed.retrieved_at)

  return (
    <div className="fc-panel fc-live">
      <div className="fc-live-head">
        <span className="fc-mark" aria-hidden="true">
          <IconFlame width={17} height={17} />
        </span>
        <span className="fc-wordmark">FIRETRACE</span>
      </div>

      {/* Two segments, nothing more. The active one is the current surface. */}
      <div className="fc-seg" role="group" aria-label="Data source">
        <button
          type="button"
          className="fc-seg-btn"
          aria-pressed={!isPast}
          onClick={() => {
            setPickerOpen(false)
            onSelectLive()
          }}
        >
          <span className={`fc-dot fc-dot-${tone === 'warn' ? 'warn' : 'ok'}`} aria-hidden="true" />
          Live
        </button>

        <div className="fc-seg-wrap" ref={pickerRef}>
          <button
            type="button"
            className="fc-seg-btn"
            aria-pressed={isPast}
            aria-expanded={pickerOpen}
            aria-controls={pickerId}
            aria-haspopup="listbox"
            onClick={() => setPickerOpen((open) => !open)}
          >
            Past data
            <IconChevronDown width={13} height={13} aria-hidden="true" />
          </button>

          {pickerOpen && (
            <div className="fc-pop fc-ranges" id={pickerId} role="listbox" aria-label="Saved periods">
              {(ranges ?? []).length === 0 ? (
                <p className="fc-pop-empty">No saved periods yet.</p>
              ) : (
                (ranges ?? []).map((range) => (
                  <button
                    key={range.id}
                    type="button"
                    role="option"
                    aria-selected={activeRange?.id === range.id}
                    className="fc-range"
                    onClick={() => {
                      onSelectRange(range)
                      setPickerOpen(false)
                    }}
                  >
                    <span className="fc-range-label">{range.label}</span>
                    <span className="fc-range-meta">
                      {range.days} {range.days === 1 ? 'day' : 'days'} ·{' '}
                      {range.detections.toLocaleString('en-IN')}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>

      {/* The freshness line. Quiet, real, and always present in Live. */}
      {line === null ? (
        <div className="fc-skel fc-skel-line" style={{ width: '62%', marginTop: 'var(--sp-2)' }} />
      ) : (
        <div className="fc-freshwrap">
          <button
            type="button"
            className={`fc-fresh fc-fresh-${tone}`}
            aria-describedby={tipOpen ? tipId : undefined}
            onMouseEnter={() => setTipOpen(true)}
            onMouseLeave={() => setTipOpen(false)}
            onFocus={() => setTipOpen(true)}
            onBlur={() => setTipOpen(false)}
            onClick={() => setTipOpen((open) => !open)}
          >
            {line}
          </button>

          {tipOpen && (
            <div className="fc-tip" role="tooltip" id={tipId}>
              {exact ? (
                <>
                  <div className="fc-tip-row">
                    <span>Satellite observation</span>
                    <b>{exact.ist}</b>
                  </div>
                  <div className="fc-tip-row">
                    <span />
                    <b>{exact.utc}</b>
                  </div>
                </>
              ) : (
                <div className="fc-tip-row">
                  <span>Satellite observation</span>
                  <b>none in this window</b>
                </div>
              )}
              {retrieved && (
                <div className="fc-tip-row">
                  <span>Checked</span>
                  <b>{retrieved.ist}</b>
                </div>
              )}
              <div className="fc-tip-sep" />
              <p className="fc-tip-note">{feed.source ?? 'NASA FIRMS'}</p>
              <p className="fc-tip-note">{feed.latency_note}</p>
            </div>
          )}
        </div>
      )}

      {/* First run with nothing saved and no network: a calm inline route out,
          never a popup. */}
      {state === 'unavailable' && (ranges ?? []).length > 0 && (
        <button type="button" className="fc-inline-link" onClick={() => setPickerOpen(true)}>
          View past data
        </button>
      )}

      {/* The one summary line. Three numbers, which is the budget. */}
      {counts && (
        <p className="fc-summary">
          <b>{counts.needs_attention}</b> need attention
          <span className="fc-sep"> · </span>
          <b>{counts.watch}</b> watch
          <span className="fc-sep"> · </span>
          <b>{counts.normal}</b> normal
        </p>
      )}
    </div>
  )
}

/**
 * The replay indicator: a single thin accent rule along the top edge.
 *
 * Pass 2 also floated a badge here repeating "Past data · <range> — no alerts
 * are sent", which the freshness line in the card already says. Two copies of
 * one message is clutter, and the floating one also collided with the search
 * bar. The rule carries the "this is not live" signal visually; the card
 * carries the words.
 */
export function PastBanner({ provenance }) {
  if (provenance?.surface !== 'past') return null
  return <div className="fc-past-rule" role="presentation" />
}
