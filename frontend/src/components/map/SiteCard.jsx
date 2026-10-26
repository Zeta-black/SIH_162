import { useEffect, useRef, useState } from 'react'
import {
  IconCheck,
  IconCheckCircle,
  IconClose,
  IconDot,
  IconRing,
} from './mapicons.jsx'

/**
 * The detail card.
 *
 * Content budget is the whole point: a status chip, one plain-language verdict,
 * at most three "why" lines, the heat band, and the uncertainty note. About
 * sixty words, no scrolling on a laptop. Everything quantitative is one click
 * away in the evidence drawer.
 *
 * On a phone this is a bottom sheet with three snap points and a drag handle.
 */

const STATUS_VAR = {
  needs_attention: 'var(--s-attn)',
  watch: 'var(--s-watch)',
  normal: 'var(--s-normal)',
  not_sure: 'var(--s-unsure)',
}

/* The class in plain words, as text only.
 * Colour is reserved for status, so the class never competes for it. */
const CLASS_WORDS = {
  INDUSTRIAL_FIRE: 'Industrial fire',
  GAS_FLARE_OR_INDUSTRIAL_HEAT: 'Routine flare or process heat',
  AGRICULTURAL_BURNING: 'Crop burning',
  NATURAL_FIRE: 'Forest or vegetation fire',
  MINING_COAL_FIRE: 'Mining or coal fire',
  UNKNOWN: 'Not sure',
}

const SNAP_POINTS = ['peek', 'half', 'full']

export default function SiteCard({
  site,
  onClose,
  onEvidence,
  onReview,
  reviewed,
  onCopyLink,
  isPast,
}) {
  const [snap, setSnap] = useState('half')
  const [copied, setCopied] = useState(false)
  const startY = useRef(null)

  useEffect(() => {
    setSnap('half')
    setCopied(false)
  }, [site?.id])

  if (!site) return null

  const classWord = CLASS_WORDS[site.predicted_class] ?? 'Other'

  /* Drag handle: three snap points rather than free dragging. Free-drag sheets
     need momentum physics to feel right, and a sheet that lands between states
     is worse than one that snaps. */
  const onTouchStart = (event) => {
    startY.current = event.touches[0].clientY
  }
  const onTouchEnd = (event) => {
    if (startY.current === null) return
    const delta = event.changedTouches[0].clientY - startY.current
    startY.current = null
    if (Math.abs(delta) < 24) return
    const index = SNAP_POINTS.indexOf(snap)
    const next = delta < 0 ? index + 1 : index - 1
    if (next < 0) onClose()
    else setSnap(SNAP_POINTS[Math.min(next, SNAP_POINTS.length - 1)])
  }

  const copy = async () => {
    const ok = await onCopyLink()
    setCopied(ok)
    if (ok) setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div
      className={`fc-panel fc-sitecard fc-snap-${snap}`}
      role="dialog"
      aria-label={`${site.status_label}: ${site.title}`}
    >
      <button
        type="button"
        className="fc-sheet-handle"
        aria-label="Resize panel"
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        onClick={() => setSnap(snap === 'full' ? 'half' : 'full')}
      >
        <span />
      </button>

      <header className="fc-card-head">
        <div className="fc-card-headtext">
          <h2 className="fc-card-title">{site.title}</h2>
          <p className="fc-card-sub">{site.subtitle}</p>
        </div>
        <button type="button" className="fc-iconbtn fc-iconbtn-sm" onClick={onClose} aria-label="Close details">
          <IconClose width={15} height={15} />
        </button>
      </header>

      <div className="fc-card-body">
        <div className="fc-card-chips">
          <span className={`fc-status fc-status-${site.status}`}>
            <IconDot width={9} height={9} aria-hidden="true" />
            {site.status_label}
          </span>

          {/* The PS-162 R2 distinction, stated on the card itself. */}
          {site.persistent ? (
            <span className="fc-badge" title="Heat recorded here on several separate days">
              <IconRing width={12} height={12} aria-hidden="true" />
              Persistent source · seen on {site.distinct_days} days
            </span>
          ) : site.history_available && site.distinct_days === 0 ? (
            <span className="fc-badge" title="No earlier heat recorded at this location">
              New heat
            </span>
          ) : null}
        </div>

        <p className="fc-verdict">{site.verdict}</p>

        <p className="fc-classline">
          Classified as <b>{classWord}</b>
          {site.abstained ? ' — below the reporting threshold' : ''}
        </p>

        {site.why?.length > 0 && (
          <ul className="fc-why">
            {site.why.slice(0, 3).map((line) => (
              <li key={line}>
                <IconCheck width={13} height={13} aria-hidden="true" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        )}

        <HeatBand site={site} />

        {site.missing?.length > 0 && (
          <p className="fc-unsure">
            <b>Not sure about:</b> {site.missing.slice(0, 2).join('. ')}.
          </p>
        )}
      </div>

      <footer className="fc-card-actions">
        <button type="button" className="fc-btn" onClick={onEvidence}>
          See evidence
        </button>
        <button
          type="button"
          className="fc-btn fc-btn-primary"
          onClick={onReview}
          disabled={reviewed || isPast}
          title={isPast ? 'Reviewing is disabled while viewing past data' : undefined}
        >
          {reviewed ? (
            <>
              <IconCheckCircle width={14} height={14} aria-hidden="true" />
              Reviewed
            </>
          ) : (
            'Mark reviewed'
          )}
        </button>
        <button
          type="button"
          className="fc-iconbtn fc-iconbtn-sm fc-copy"
          onClick={copy}
          aria-label="Copy link to this site"
          title="Copy link"
        >
          {copied ? <IconCheck width={14} height={14} /> : <LinkGlyph />}
        </button>
      </footer>
    </div>
  )
}

const LinkGlyph = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" />
    <path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" />
  </svg>
)

/**
 * Today's heat against what this location normally does.
 *
 * When the baseline could not be assessed, no band is drawn — only the reading.
 * An invented "normal range" would be the single most misleading pixel on the
 * screen, so the honest version of this chart is sometimes no chart.
 */
function HeatBand({ site }) {
  const frp = site.frp_max_mw
  if (frp === null || frp === undefined) {
    return (
      <div className="fc-band">
        <p className="fc-band-label">Heat output</p>
        <p className="fc-band-note">Radiative power was not reported for this detection.</p>
      </div>
    )
  }

  const assessed = site.abnormality_status === 'assessed'
  const range = site.baseline_range
  const hasBand = assessed && range && range.max > 0

  const scaleMax = Math.max(frp * 1.25, hasBand ? range.max * 1.6 : 40)
  const pct = (value) => Math.min(100, Math.max(0, (value / scaleMax) * 100))

  return (
    <div className="fc-band">
      <p className="fc-band-label">Heat output</p>
      <div
        className="fc-band-track"
        role="img"
        aria-label={
          hasBand
            ? `Peak ${frp.toFixed(1)} megawatts against a usual range of ${range.min.toFixed(1)} to ${range.max.toFixed(1)}`
            : `Peak ${frp.toFixed(1)} megawatts, no usual range established`
        }
      >
        {hasBand && (
          <span
            className="fc-band-usual"
            style={{ left: `${pct(range.min)}%`, width: `${pct(range.max) - pct(range.min)}%` }}
          />
        )}
        <span
          className="fc-band-marker"
          style={{ left: `calc(${pct(frp)}% - 2px)`, background: STATUS_VAR[site.status] }}
        />
      </div>
      <p className="fc-band-note">
        {hasBand ? (
          <>
            Peak <b>{frp.toFixed(1)} MW</b>. Usual range here {range.min.toFixed(1)}–
            {range.max.toFixed(1)} MW over {site.distinct_days} days.
          </>
        ) : (
          <>
            Peak <b>{frp.toFixed(1)} MW</b>. Too little history at this location to
            establish a usual range, so none is drawn.
          </>
        )}
      </p>
    </div>
  )
}
