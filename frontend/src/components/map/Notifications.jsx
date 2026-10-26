import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { IconBell, IconClose, IconInfo, IconSettings } from './mapicons.jsx'

/**
 * The notification surfaces: bell, panel, toast and the small settings sheet.
 *
 * Policy lives in docs/NOTIFICATION_POLICY.md and is enforced in the backend.
 * These components only render what the API already decided to send — they never
 * invent an item and never decide severity. In Past data mode the backend
 * returns a preview instead of real items, and the panel labels it as such.
 */

const reduceMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

function age(iso) {
  if (!iso) return ''
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (Number.isNaN(minutes)) return ''
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.floor(hours / 24)} d ago`
}

// ------------------------------------------------------------------ bell
export function NotificationBell({
  items,
  counts,
  preview,
  isPast,
  onOpenSite,
  onAction,
  onTest,
  webhookConfigured,
  policy,
}) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState('attention')
  const [permission, setPermission] = useState(
    typeof Notification !== 'undefined' ? Notification.permission : 'unsupported',
  )
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const panelRef = useRef(null)

  useEffect(() => {
    const away = (event) => {
      if (panelRef.current && !panelRef.current.contains(event.target)) {
        setOpen(false)
        setSettingsOpen(false)
      }
    }
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setOpen(false)
        setSettingsOpen(false)
      }
    }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  const grouped = useMemo(() => {
    const source = isPast ? preview ?? [] : items ?? []
    return {
      attention: source.filter((item) => item.group !== 'system'),
      system: source.filter((item) => item.group === 'system'),
    }
  }, [items, preview, isPast])

  const unread = isPast ? 0 : counts?.unread ?? 0
  const visible = grouped[tab]

  /* Permission is requested only on this click. Asking on page load is the
     fastest way to get permanently blocked, and it is rude. */
  const askPermission = async () => {
    if (typeof Notification === 'undefined') return
    const result = await Notification.requestPermission()
    setPermission(result)
  }

  const runTest = async () => {
    setTestResult('sending')
    try {
      const result = await onTest()
      setTestResult(result?.webhook?.sent ? 'sent' : 'queued')
    } catch {
      setTestResult('failed')
    }
  }

  return (
    <div className="fc-bellwrap" ref={panelRef}>
      <button
        type="button"
        className="fc-iconbtn fc-bell"
        aria-label={
          unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'
        }
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <IconBell width={17} height={17} />
        {unread > 0 && <span className="fc-bell-dot" aria-hidden="true" />}
      </button>

      {open && (
        <div className="fc-pop fc-notifpanel" role="dialog" aria-label="Notifications">
          <header className="fc-notif-head">
            <span className="fc-notif-title">Notifications</span>
            <button
              type="button"
              className="fc-iconbtn fc-iconbtn-sm"
              aria-label="Notification settings"
              aria-expanded={settingsOpen}
              onClick={() => setSettingsOpen((value) => !value)}
            >
              <IconSettings width={15} height={15} />
            </button>
          </header>

          {/* In replay the panel shows what would have fired and says so. */}
          {isPast && (
            <p className="fc-notif-replay">
              Would have alerted — this is a replay. Nothing was sent.
            </p>
          )}

          <div className="fc-tabs" role="tablist">
            {[
              ['attention', 'Needs attention', grouped.attention.length],
              ['system', 'System', grouped.system.length],
            ].map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                className="fc-tab"
                onClick={() => setTab(key)}
              >
                {label}
                {count > 0 && <span className="fc-tab-n">{count}</span>}
              </button>
            ))}
          </div>

          {settingsOpen && (
            <div className="fc-notif-settings">
              <button
                type="button"
                className="fc-btn fc-btn-quiet"
                onClick={askPermission}
                disabled={permission === 'granted' || permission === 'unsupported'}
              >
                {permission === 'granted'
                  ? 'Browser alerts enabled'
                  : permission === 'denied'
                    ? 'Browser alerts blocked in this browser'
                    : 'Enable browser alerts'}
              </button>

              <button type="button" className="fc-btn fc-btn-quiet" onClick={runTest}>
                {testResult === 'sending' ? 'Sending test…' : 'Send test alert'}
              </button>

              {testResult && testResult !== 'sending' && (
                <p className="fc-notif-hint">
                  {testResult === 'sent'
                    ? 'Test sent to your webhook, labelled TEST.'
                    : testResult === 'queued'
                      ? 'Test added to this panel, labelled TEST. No webhook is configured.'
                      : 'Test failed. See the server log.'}
                </p>
              )}

              <p className="fc-notif-hint">
                Webhook: {webhookConfigured ? 'configured' : 'not configured'}. Policy{' '}
                {policy?.policy_version ?? '—'}.
              </p>
            </div>
          )}

          <div className="fc-notif-list">
            {visible.length === 0 ? (
              <p className="fc-notif-empty">
                {tab === 'attention'
                  ? 'Nothing needs attention. That is good news.'
                  : 'No system notices.'}
              </p>
            ) : (
              visible.map((item) => (
                <article key={item.id} className={`fc-notif fc-notif-${item.severity}`}>
                  <div className="fc-notif-row">
                    <span className={`fc-notif-pip fc-notif-pip-${item.severity}`} aria-hidden="true" />
                    <h3 className="fc-notif-h">
                      {item.is_test && <span className="fc-testtag">TEST</span>}
                      {item.title}
                    </h3>
                  </div>
                  <p className="fc-notif-body">{item.body}</p>
                  <div className="fc-notif-foot">
                    <span className="fc-notif-age" title={item.reason_code}>
                      {age(item.created_at)}
                    </span>
                    {!isPast && (
                      <span className="fc-notif-actions">
                        {item.site_id && (
                          <button type="button" onClick={() => onOpenSite(item.site_id)}>
                            Open on map
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => onAction(item.id, 'acknowledge')}
                        >
                          Acknowledge
                        </button>
                        <button type="button" onClick={() => onAction(item.id, 'snooze')}>
                          Snooze 6 h
                        </button>
                      </span>
                    )}
                  </div>
                </article>
              ))
            )}
          </div>

          <footer className="fc-notif-foot-note">
            <IconInfo width={12} height={12} aria-hidden="true" />
            <span>
              Normal, Watch and Not sure stay on the map and never notify.
            </span>
          </footer>
        </div>
      )}
    </div>
  )
}

// ----------------------------------------------------------------- toast
/**
 * One toast at a time, bottom-left, high severity only.
 *
 * Bottom-left because the detail card is on the right and a toast must never
 * cover it. Under reduced-motion the toast is not shown at all — the item is
 * still in the bell, which is the durable surface.
 */
export function NotificationToast({ item, onOpen, onDismiss }) {
  useEffect(() => {
    if (!item) return undefined
    const timer = setTimeout(onDismiss, 8000)
    return () => clearTimeout(timer)
  }, [item, onDismiss])

  if (!item || reduceMotion()) return null

  return (
    <div className="fc-toast" role="status">
      <span className="fc-notif-pip fc-notif-pip-high" aria-hidden="true" />
      <div className="fc-toast-text">
        <strong>
          {item.is_test && <span className="fc-testtag">TEST</span>}
          {item.title}
        </strong>
        <span>{item.body}</span>
      </div>
      {item.site_id && (
        <button type="button" className="fc-toast-open" onClick={() => onOpen(item.site_id)}>
          Open
        </button>
      )}
      <button type="button" className="fc-iconbtn fc-iconbtn-sm" onClick={onDismiss} aria-label="Dismiss">
        <IconClose width={13} height={13} />
      </button>
    </div>
  )
}

/**
 * Raise a browser notification for a high-severity item, once.
 *
 * Only ever called for items the backend created, and never in replay —
 * `alerts_suppressed` means the backend returned a preview, which this hook is
 * never given.
 */
export function useBrowserNotifications(items, enabled) {
  const sent = useRef(new Set())

  useEffect(() => {
    if (!enabled) return
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return

    for (const item of items ?? []) {
      if (item.severity !== 'high' || sent.current.has(item.id)) continue
      sent.current.add(item.id)
      try {
        // eslint-disable-next-line no-new
        new Notification(`FIRETRACE · ${item.title}`, {
          body: item.body,
          tag: item.id,
        })
      } catch {
        // Some browsers refuse construction outside a service worker; the item
        // is already in the bell either way.
      }
    }
  }, [items, enabled])
}

/** A small "N new" pill, shown when items arrived while the user was elsewhere. */
export function NewItemsPill({ count, onClick }) {
  if (!count) return null
  return (
    <button type="button" className="fc-newpill" onClick={onClick}>
      {count} new
    </button>
  )
}

export function useNotificationFeed(api, { isPast, pollMs = 45000 }) {
  const [items, setItems] = useState([])
  const [counts, setCounts] = useState({ unread: 0, open: 0 })
  const [policy, setPolicy] = useState(null)
  const [webhookConfigured, setWebhookConfigured] = useState(false)
  const [toast, setToast] = useState(null)
  const seenIds = useRef(new Set())
  const firstLoad = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const data = await api.notifications()
      setItems(data.items ?? [])
      setCounts(data.counts ?? { unread: 0, open: 0 })
      setPolicy(data.policy ?? null)
      setWebhookConfigured(Boolean(data.webhook_configured))

      // Toast only for items that appeared after the first load, so opening the
      // app does not fire a volley of toasts for a backlog.
      const high = (data.items ?? []).filter(
        (item) => item.severity === 'high' && item.state === 'created',
      )
      if (!firstLoad.current && !isPast) {
        const fresh = high.find((item) => !seenIds.current.has(item.id))
        if (fresh) setToast(fresh)
      }
      for (const item of data.items ?? []) seenIds.current.add(item.id)
      firstLoad.current = false
    } catch {
      // The bell is not worth breaking the map over.
    }
  }, [api, isPast])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, pollMs)
    return () => clearInterval(timer)
  }, [refresh, pollMs])

  return {
    items,
    counts,
    policy,
    webhookConfigured,
    toast,
    dismissToast: () => setToast(null),
    refresh,
  }
}
