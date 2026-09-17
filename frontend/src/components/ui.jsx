// Console primitives.
//
// Two of these carry policy rather than styling:
//   <Provenance>  attaches source and processing to any figure whose numbers
//                 came from outside this machine.
//   <ErrorState>  renders a real failure with a retry. No code path in this
//                 application answers a failed request with invented data.

import { IconAlert } from './icons.jsx'

export function Module({ title, icon, note, actions, children, flush = false, className = '' }) {
  return (
    <section className={className ? `mod ${className}` : 'mod'}>
      {(title || actions || note) && (
        <header className="mod-head">
          <span className="mod-title">
            {icon}
            {title}
          </span>
          {actions ?? (note && <span className="mod-note">{note}</span>)}
        </header>
      )}
      <div className={flush ? 'mod-body-flush' : 'mod-body'}>{children}</div>
    </section>
  )
}

export function Group({ title, note, children }) {
  return (
    <section className="group">
      <div className="group-head">
        <h2>{title}</h2>
        {note && <span className="group-note">{note}</span>}
      </div>
      {children}
    </section>
  )
}

export function Metric({ label, value, unit, sub, tone }) {
  const cls = tone === 'alarm' ? 'metric metric-alarm' : tone === 'warn' ? 'metric metric-warn' : 'metric'
  return (
    <div className={cls}>
      <div className="metric-k">{label}</div>
      <div className="metric-v">
        {value}
        {unit && <span className="metric-u">{unit}</span>}
      </div>
      {sub && <div className="metric-s">{sub}</div>}
    </div>
  )
}

/** Colour plus a three-letter code, so identity never rests on hue alone. */
export function ClassMark({ cls, label = true }) {
  if (!cls) return <span className="na">unclassified</span>
  return (
    <span className="row" style={{ gap: 6, minWidth: 0 }}>
      <span className="code" style={{ color: cls.color }}>
        {cls.code}
      </span>
      {label && <span className="trunc">{cls.label}</span>}
    </span>
  )
}

export function Priority({ level, score }) {
  return (
    <span className={`pri pri-${String(level).toLowerCase()}`}>
      {score != null ? score.toFixed(2) : level}
    </span>
  )
}

export function Spinner({ large = false }) {
  return <span className={large ? 'spin spin-lg' : 'spin'} aria-hidden="true" />
}

export function Loading({ label = 'Loading…' }) {
  return (
    <div className="state" role="status">
      <Spinner large />
      <p>{label}</p>
    </div>
  )
}

export function ErrorState({ error, onRetry, what = 'this view' }) {
  const message = error?.message ?? String(error ?? 'Unknown error')
  return (
    <div className="state" role="alert">
      <IconAlert style={{ width: 24, height: 24, color: 'var(--alarm)' }} />
      <h3>Could not load {what}</h3>
      <p>{message}</p>
      <p className="faint xs">No substitute data is shown in place of a failed request.</p>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children }) {
  return (
    <div className="state">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  )
}

export function Note({ kind = 'plain', icon = true, children }) {
  const colour =
    kind === 'warn' ? 'var(--warn)' : kind === 'alarm' ? 'var(--alarm)' : kind === 'info' ? 'var(--accent)' : 'var(--ink-3)'
  return (
    <div className={`note note-${kind}`}>
      {icon && <IconAlert style={{ color: colour }} />}
      <div>{children}</div>
    </div>
  )
}

/** Source attribution for a figure. Omitted fields are not rendered. */
export function Provenance({ source, observed, retrieved, processing, note, licence }) {
  const rows = [
    ['Source', source],
    ['Observed', observed],
    ['Retrieved', retrieved],
    ['Process', processing],
    ['Licence', licence],
  ].filter(([, v]) => v)
  if (!rows.length && !note) return null
  return (
    <dl className="prov">
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: 'contents' }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
      {note && (
        <div style={{ display: 'contents' }}>
          <dt />
          <dd>{note}</dd>
        </div>
      )}
    </dl>
  )
}

/**
 * Horizontal magnitude bar. The value is always printed beside the bar, so the
 * figure survives print, forced-colours mode and colour-vision deficiency.
 */
export function Bar({ label, value, max, display, color = 'var(--accent)', labelWidth = 150 }) {
  const pct = max > 0 ? Math.max(1.5, (value / max) * 100) : 0
  return (
    <div className="bar">
      <span className="bar-k" style={{ width: labelWidth }}>
        {label}
      </span>
      <span className="bar-t">
        <span className="bar-f" style={{ width: `${pct}%`, background: color }} />
      </span>
      <span className="bar-v" style={{ width: 48 }}>
        {display}
      </span>
    </div>
  )
}

export function PipeNode({ index, title, meta, children }) {
  return (
    <div className="pipe-n">
      <div className="pipe-i">{index}</div>
      <div className="pipe-t">{title}</div>
      <div className="pipe-d">{children}</div>
      {meta && <div className="pipe-m">{meta}</div>}
    </div>
  )
}
