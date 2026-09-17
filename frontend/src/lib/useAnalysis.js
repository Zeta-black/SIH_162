import { useEffect, useRef } from 'react'
import { api } from '../api.js'
import { useApi, useDebounced } from './useApi.js'

/**
 * Runs the classified-hotspot analysis for the current area and window, and
 * reports what it rendered up to the console shell so the masthead chip and
 * the status strip always describe the data actually on screen.
 *
 * The query is debounced because a miss costs a real round trip to NASA and
 * OpenStreetMap; changing a control should produce one request, not six.
 */
export function useAnalysis({ query, reportStatus, limit = 900, enabled = true, refreshToken = 0 }) {
  const settled = useDebounced(query, 350)
  const started = useRef(0)
  const elapsed = useRef(null)

  const result = useApi(
    ({ signal } = {}) => {
      started.current = performance.now()
      return api
        .hotspots({ ...settled, limit, refresh: refreshToken > 0 ? true : undefined }, { signal })
        .then((data) => {
          elapsed.current = (performance.now() - started.current) / 1000
          return data
        })
    },
    [settled.bbox, settled.days, settled.mode, limit, refreshToken],
    { enabled, keepPrevious: true },
  )

  useEffect(() => {
    if (!reportStatus) return
    reportStatus({
      status: result.data?.status ?? null,
      summary: result.data?.summary ?? null,
      error: result.error,
      loading: result.loading,
      latency: result.loading ? undefined : elapsed.current,
    })
  }, [result.data, result.error, result.loading, reportStatus])

  return result
}
