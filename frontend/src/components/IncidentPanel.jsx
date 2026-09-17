import { useState } from 'react'
import { api } from '../api.js'
import { utcAndIst } from '../lib/format.js'
import { Module, Note } from './ui.jsx'
import { IconAlert } from './icons.jsx'

const ACTION_LABELS = {
  acknowledge: 'Acknowledge',
  dispatch: 'Dispatch team',
  monitor: 'Monitor',
  resolve: 'Resolve',
  dismiss: 'Dismiss',
  reopen: 'Reopen',
}

// Actions that move the incident on, in the order an operator works through them.
const TRANSITION_ORDER = ['acknowledge', 'dispatch', 'monitor', 'resolve', 'reopen', 'dismiss']

export function StatusChip({ status }) {
  return <span className={`st st-${String(status).toLowerCase()}`}>{status}</span>
}

export function AlertChip({ level }) {
  if (!level) return null
  return <span className={`alert-lvl alert-${String(level).toLowerCase()}`}>{level}</span>
}

/**
 * The response side of an incident: what state it is in, what an operator may
 * do next, and an append-only record of everything already done.
 *
 * The buttons offered come from the backend's `available_actions`, which the
 * state machine derives — the interface never guesses at a transition the
 * server would reject.
 */
export default function IncidentPanel({ incident, onChanged }) {
  const [actor, setActor] = useState('operator')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  if (!incident) return null

  const available = incident.available_actions ?? []
  const transitions = TRANSITION_ORDER.filter((a) => available.includes(a))

  const run = async (action) => {
    setBusy(action)
    setError(null)
    try {
      const updated = await api.incidentAction(incident.event_id, {
        action,
        actor: actor.trim() || 'operator',
        note: note.trim() || null,
      })
      setNote('')
      onChanged?.(updated)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <Module
        title="Response"
        icon={<IconAlert />}
        note={incident.assigned_to ? `assigned: ${incident.assigned_to}` : 'unassigned'}
      >
        <div className="between" style={{ marginBottom: 10 }}>
          <StatusChip status={incident.status} />
          <AlertChip level={incident.alert_level} />
        </div>

        {incident.alert_reasons?.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div className="cmd-label" style={{ marginBottom: 4 }}>
              Why this alerted
            </div>
            <ul style={{ margin: 0, paddingLeft: 15, fontSize: 11, lineHeight: 1.6 }}>
              {incident.alert_reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="cmd-label" style={{ marginBottom: 4 }}>
          Operator
        </div>
        <input
          className="sel"
          style={{ width: '100%', cursor: 'text', background: 'var(--panel)' }}
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="Name for the audit log"
        />

        <div className="cmd-label" style={{ margin: '8px 0 4px' }}>
          Note / assignee
        </div>
        <input
          className="sel"
          style={{ width: '100%', cursor: 'text', background: 'var(--panel)' }}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Optional — used as the assignee for Assign"
        />

        <div className="row wrap" style={{ gap: 6, marginTop: 10 }}>
          {transitions.map((a) => (
            <button
              key={a}
              className={a === 'acknowledge' || a === 'resolve' ? 'btn btn-go' : 'btn'}
              disabled={busy !== null}
              onClick={() => run(a)}
            >
              {busy === a && <span className="spin" style={{ borderTopColor: '#fff' }} />}
              {ACTION_LABELS[a] ?? a}
            </button>
          ))}
          {available.includes('assign') && (
            <button className="btn" disabled={busy !== null || !note.trim()} onClick={() => run('assign')}>
              Assign
            </button>
          )}
          {available.includes('note') && (
            <button className="btn" disabled={busy !== null || !note.trim()} onClick={() => run('note')}>
              Add note
            </button>
          )}
        </div>

        {error && (
          <div style={{ marginTop: 9 }}>
            <Note kind="alarm">{error.message}</Note>
          </div>
        )}

        <p className="xs faint" style={{ marginTop: 9, lineHeight: 1.5 }}>
          Alerts are raised in this dashboard only — no email, SMS or webhook delivery is
          implemented. There is no authentication, so the operator name is recorded for
          traceability, not as proof of identity.
        </p>
      </Module>

      <Module title="Action log" note={`${incident.actions?.length ?? 0} entries`}>
        <div className="log">
          {(incident.actions ?? [])
            .slice()
            .reverse()
            .map((a) => (
              <div className="log-row" key={a.id}>
                <div className="log-head">
                  <span className="log-actor">{a.actor}</span>
                  <span>{a.action}</span>
                  {a.from_status !== a.to_status && (
                    <span className="m" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                      {a.from_status ?? '—'} → {a.to_status}
                    </span>
                  )}
                  <span className="log-time">{utcAndIst(a.at).ist.replace(' IST', '')}</span>
                </div>
                {a.note && <div className="log-note">{a.note}</div>}
              </div>
            ))}
        </div>
        <p className="xs faint" style={{ marginTop: 8 }}>
          Append-only. Transitions are validated server-side, so this log cannot contain an
          impossible sequence such as a resolve that nobody acknowledged.
        </p>
      </Module>
    </>
  )
}
