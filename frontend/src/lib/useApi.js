import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * One fetching hook for the whole app, so every screen gets the same five
 * states: idle, loading, success, empty and error — with a working retry.
 *
 * There is deliberately no fallback data path. If a request fails the caller
 * renders the failure; it never substitutes invented values, because a chart
 * that silently switches to made-up numbers is worse than a visible error.
 */
export function useApi(fetcher, deps = [], options = {}) {
  const { enabled = true, keepPrevious = false } = options

  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(enabled)
  const [fetchedAt, setFetchedAt] = useState(null)

  // Guards against a slow earlier request landing after a newer one.
  const seq = useRef(0)
  const mounted = useRef(true)
  const controller = useRef(null)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      controller.current?.abort()
    }
  }, [])

  const load = useCallback(async () => {
    if (!enabled) return
    controller.current?.abort()
    controller.current = new AbortController()
    const id = ++seq.current
    setLoading(true)
    setError(null)
    if (!keepPrevious) setData(null)
    try {
      const result = await fetcher({ signal: controller.current.signal })
      if (!mounted.current || id !== seq.current) return
      setData(result)
      setFetchedAt(new Date())
    } catch (err) {
      if (!mounted.current || id !== seq.current) return
      setError(err)
      setData(null)
    } finally {
      if (mounted.current && id === seq.current) setLoading(false)
    }
    // fetcher identity is controlled by the caller's deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, keepPrevious, ...deps])

  useEffect(() => {
    load()
  }, [load])

  return { data, error, loading, fetchedAt, reload: load }
}

/**
 * Debounce a rapidly changing value.
 *
 * The analysis request is expensive — it reaches NASA and OpenStreetMap — so
 * dragging a control must not fire one request per intermediate value. An
 * earlier build did exactly that and queued several minute-long requests.
 */
export function useDebounced(value, delay = 450) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return settled
}
