import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'

/**
 * The basemap.
 *
 * NOT CARTO. CARTO's raster basemaps (`basemaps.cartocdn.com/rastertiles/...`
 * and the older `cartodb-basemaps-*` hosts) now require an API key, and the
 * failure mode is vicious: they answer HTTP 200 with a valid 2049-byte PNG that
 * reads "API KEY REQUIRED" diagonally across the tile. Verified on
 * 2026-10-25 for voyager and light_all alike. No status check, health probe or
 * smoke test can catch that — it is only visible by looking at the map, which
 * is precisely when it would be a judge looking at it.
 *
 * OpenStreetMap's own tiles need no key. The soft, recessive look is produced
 * in CSS (see .m-tiles below) rather than by paying for a "light" style, which
 * keeps the basemap quiet so the status colours are the only strong colour on
 * screen.
 */
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

// India's land extent, used with fitBounds so the subject fills the frame at
// any viewport size. A fixed centre+zoom put Arabia and southern China on
// screen at 1366x768, which is the primary demo resolution.
const INDIA_BOUNDS = [
  [6.5, 68.0],
  [36.0, 97.5],
]
const INDIA_CENTER = [22.6, 80.0]
const INDIA_ZOOM = 5

// Below this zoom, nearby sites are merged into a count bubble so the national
// view stays calm. Above it, individual sites are drawn.
const CLUSTER_MAX_ZOOM = 8

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Marker diameter. Needs-attention reads largest; normal recedes. */
const SIZE = {
  needs_attention: 18,
  not_sure: 14,
  watch: 14,
  normal: 10,
}

const RANK = { needs_attention: 0, not_sure: 1, watch: 2, normal: 3 }

function siteIcon(site, { selected, pulse }) {
  const size = SIZE[site.status] ?? 12
  const classes = [
    'm-marker',
    `m-marker-${site.status}`,
    selected ? 'm-marker-selected' : '',
    pulse ? 'm-marker-pulse' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return L.divIcon({
    className: '',
    html: `<div class="${classes}" style="width:${size}px;height:${size}px"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

function clusterIcon(count, worst) {
  const size = count > 99 ? 40 : count > 20 ? 36 : 32
  const attn = worst === 'needs_attention'
  return L.divIcon({
    className: '',
    html: `<div class="m-cluster ${attn ? 'm-cluster-attn' : ''}" style="width:${size}px;height:${size}px">${count}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

/**
 * Grid clustering.
 *
 * Deliberately not a new dependency. leaflet.markercluster would add ~30 KB and
 * an animation style that fights the calm look; a fixed grid in degrees is
 * predictable, fast for a few hundred sites, and good enough because the only
 * job here is "do not show 390 dots over India at zoom 5".
 */
function clusterSites(sites, zoom) {
  if (zoom > CLUSTER_MAX_ZOOM) return sites.map((s) => ({ kind: 'site', site: s }))

  const cell = 360 / Math.pow(2, zoom + 2)
  const buckets = new Map()

  for (const s of sites) {
    const key = `${Math.floor(s.lat / cell)}:${Math.floor(s.lon / cell)}`
    const bucket = buckets.get(key)
    if (bucket) bucket.push(s)
    else buckets.set(key, [s])
  }

  const out = []
  for (const group of buckets.values()) {
    if (group.length === 1) {
      out.push({ kind: 'site', site: group[0] })
      continue
    }
    // A cluster sits at the mean position and reports the most urgent status
    // it contains, so a single red site is never hidden inside a grey bubble.
    const lat = group.reduce((a, s) => a + s.lat, 0) / group.length
    const lon = group.reduce((a, s) => a + s.lon, 0) / group.length
    const worst = group.reduce(
      (acc, s) => (RANK[s.status] < RANK[acc] ? s.status : acc),
      'normal',
    )
    out.push({ kind: 'cluster', lat, lon, count: group.length, worst, sites: group })
  }
  return out
}

export default function CalmMap({ sites, selectedId, onSelect, flyTo, pulseId }) {
  const hostRef = useRef(null)
  const mapRef = useRef(null)
  const layerRef = useRef(null)
  const zoomRef = useRef(INDIA_ZOOM)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const fitRef = useRef(null)
  const didFitRef = useRef(false)
  // The map's event listeners are bound once at mount. Binding `render`
  // directly captured the first render's empty site list, so the first pan or
  // zoom cleared every marker. The ref always holds the current one.
  const renderRef = useRef(null)

  // --- create the map once -------------------------------------------------
  useEffect(() => {
    if (mapRef.current || !hostRef.current) return

    const map = L.map(hostRef.current, {
      center: INDIA_CENTER,
      zoom: INDIA_ZOOM,
      zoomControl: false,
      attributionControl: true,
      preferCanvas: false,
      // Keep the world from repeating sideways; a single India is the subject.
      worldCopyJump: false,
      minZoom: 3,
    })

    L.tileLayer(TILE_URL, {
      attribution: TILE_ATTRIBUTION,
      maxZoom: 19,
      className: 'm-tiles',
      detectRetina: true,
    }).addTo(map)

    L.control.zoom({ position: 'bottomright' }).addTo(map)

    layerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map

    /* Frame India rather than trusting a fixed zoom.
     *
     * This has to wait for layout. Called synchronously here, Leaflet measures
     * a container that has not been sized yet and picks a zoom for the wrong
     * viewport — which put Ukraine and Indonesia on screen with India a thumbnail
     * in the middle. invalidateSize() first, then fit, then keep it framed when
     * the window changes. */
    /* Framing, which took three attempts to get right.
     *
     * 1. React StrictMode mounts, unmounts and remounts in development, so a
     *    deferred callback can fire after the map was removed — which threw
     *    "Cannot set properties of undefined (setting '_leaflet_pos')". Hence
     *    the disposed guard.
     * 2. Fitting on requestAnimationFrame measured a container that was still
     *    0x0, so Leaflet clamped to minZoom. Hence waiting for a real size.
     * 3. Fitting the FIRMS query bbox (6.5N-36N) is *correctly* zoom 4 at
     *    1366x768 — which puts Arabia and Indonesia on screen. The query box is
     *    not the subject. So the fit targets the bounds of the detections we
     *    actually have, which also stops the map implying coverage we do not
     *    have. See fitRef below.
     */
    let disposed = false

    const sizeReady = () => {
      if (disposed || !map._container) return false
      map.invalidateSize({ animate: false })
      const { x, y } = map.getSize()
      return x >= 80 && y >= 80
    }

    const rafId = requestAnimationFrame(() => {
      if (sizeReady()) fitRef.current?.()
    })
    const ro = new ResizeObserver(() => {
      if (sizeReady()) fitRef.current?.()
    })
    ro.observe(hostRef.current)

    // Leaflet renders its controls as bare links; give them real names so the
    // map is usable with a screen reader.
    requestAnimationFrame(() => {
      const zin = hostRef.current?.querySelector('.leaflet-control-zoom-in')
      const zout = hostRef.current?.querySelector('.leaflet-control-zoom-out')
      zin?.setAttribute('aria-label', 'Zoom in')
      zout?.setAttribute('aria-label', 'Zoom out')
      hostRef.current
        ?.querySelector('.leaflet-container')
        ?.setAttribute('aria-label', 'Map of thermal detections across India')
    })

    const onZoom = () => {
      zoomRef.current = map.getZoom()
      renderRef.current?.()
    }
    const onMove = () => renderRef.current?.()
    map.on('zoomend', onZoom)
    map.on('moveend', onMove)

    return () => {
      disposed = true
      cancelAnimationFrame(rafId)
      ro.disconnect()
      map.off('zoomend', onZoom)
      map.off('moveend', onMove)
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- draw markers --------------------------------------------------------
  const render = useMemo(
    () => () => {
      const map = mapRef.current
      const layer = layerRef.current
      if (!map || !layer) return

      layer.clearLayers()
      const zoom = map.getZoom()

      // Draw calm statuses first so red markers always sit on top of green ones.
      const ordered = [...sites].sort((a, b) => RANK[b.status] - RANK[a.status])

      for (const item of clusterSites(ordered, zoom)) {
        if (item.kind === 'cluster') {
          L.marker([item.lat, item.lon], {
            icon: clusterIcon(item.count, item.worst),
            keyboard: false,
            interactive: true,
          })
            .addTo(layer)
            .on('click', () => {
              map.flyTo([item.lat, item.lon], Math.min(zoom + 3, 11), {
                duration: prefersReducedMotion() ? 0 : 0.6,
              })
            })
          continue
        }

        const s = item.site
        L.marker([s.lat, s.lon], {
          icon: siteIcon(s, { selected: s.id === selectedId, pulse: s.id === pulseId }),
          keyboard: false,
          // Screen readers get the status and name, not a bare pin.
          alt: `${s.status_label}: ${s.title}`,
          riseOnHover: true,
        })
          .addTo(layer)
          .on('click', () => onSelectRef.current?.(s.id))
      }
    },
    [sites, selectedId, pulseId],
  )

  useEffect(() => {
    renderRef.current = render
    render()
  }, [render])

  /* Frame the detections, once, as soon as both the container and the data are
   * ready. Falls back to India's extent when a window genuinely has none. */
  useEffect(() => {
    fitRef.current = () => {
      const map = mapRef.current
      if (!map || !map._container || didFitRef.current) return
      if (!sites.length) {
        map.fitBounds(INDIA_BOUNDS, { padding: [28, 28], animate: false })
        return // not marked as fitted: data may still arrive
      }
      const lats = sites.map((s) => s.lat)
      const lons = sites.map((s) => s.lon)
      // Asymmetric padding, because the panels are asymmetric: the brand card
      // and the filter chips occupy the top-left and top-centre, the queue the
      // bottom-left. Without this a cluster lands under the chips.
      const wide = map.getSize().x >= 1024
      map.fitBounds(
        [
          [Math.min(...lats), Math.min(...lons)],
          [Math.max(...lats), Math.max(...lons)],
        ],
        {
          paddingTopLeft: wide ? [352, 150] : [24, 150],
          paddingBottomRight: wide ? [72, 72] : [24, 120],
          maxZoom: 8,
          animate: false,
        },
      )
      didFitRef.current = true
    }
    const { x, y } = mapRef.current?.getSize?.() ?? { x: 0, y: 0 }
    if (x >= 80 && y >= 80) fitRef.current()
  }, [sites])

  // --- fly to a requested target ------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !flyTo) return
    map.flyTo([flyTo.lat, flyTo.lon], flyTo.zoom ?? 11, {
      duration: prefersReducedMotion() ? 0 : 0.7,
    })
  }, [flyTo])

  return <div className="m-canvas" ref={hostRef} />
}
