import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CircleMarker,
  Circle,
  MapContainer,
  Marker,
  Popup,
  ScaleControl,
  TileLayer,
  useMap,
} from 'react-leaflet'
import L from 'leaflet'
import { coords, km, num, pct } from '../lib/format.js'

// India is the configured SIH operational default. The map remains capable
// of showing any explicitly selected regional query.
const INDIA = [22.5, 80.5]

/**
 * Marker radius encodes fire radiative power on a square-root scale.
 *
 * The eye reads the AREA of a disc, and area grows with the square of the
 * radius — so a linear radius would exaggerate a 100 MW flare tenfold against
 * a 10 MW fire. Square-root scaling makes area proportional to power.
 *
 * A detection with no reported FRP gets the base size and is drawn hollow, so
 * "not reported" is visibly different from "small".
 */
function radiusFor(frp) {
  if (frp === null || frp === undefined) return 4
  return Math.max(4, Math.min(16, 3.5 + Math.sqrt(frp) * 1.45))
}

function FitToQuery({ bboxKey }) {
  const map = useMap()
  const lastKey = useRef(null)

  useEffect(() => {
    if (lastKey.current === bboxKey) return
    lastKey.current = bboxKey
    const [rawBbox] = bboxKey.split('|')
    const values = rawBbox.split(',').map(Number)
    if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) return
    const [west, south, east, north] = values
    map.fitBounds([[south, west], [north, east]], { padding: [44, 44], maxZoom: 7 })
  }, [bboxKey, map])

  return null
}

function PanToSelection({ events, selectedId }) {
  const map = useMap()
  useEffect(() => {
    if (!selectedId) return
    const hit = events.find((e) => e.event.event_id === selectedId)
    if (!hit) return
    // Keep the operator's zoom; only recentre.
    map.panTo([hit.event.latitude, hit.event.longitude], { animate: true })
  }, [selectedId, events, map])
  return null
}

/**
 * Basemaps, all key-free.
 *
 * An earlier build used CARTO's `basemaps.cartocdn.com` tiles. Those now
 * require an API key — and critically they still answer HTTP 200 with a valid
 * PNG, except the PNG is a grey tile stamped "API KEY REQUIRED". No status
 * check catches that; it is only visible by looking at the rendered map.
 *
 * OpenStreetMap's own tiles need no key. The default style is desaturated in
 * CSS rather than swapped for a paid "light" theme, which keeps the basemap
 * recessive so the data markers carry the colour.
 */
const BASEMAPS = {
  muted: {
    label: 'Muted',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    className: 'tiles-muted',
    maxZoom: 19,
  },
  standard: {
    label: 'Standard',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    className: '',
    maxZoom: 19,
  },
  terrain: {
    label: 'Terrain',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution:
      'Map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM &middot; style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
    className: 'tiles-terrain',
    maxZoom: 17,
  },
}

export default function MapView({
  events,
  facilities,
  selectedId,
  onSelect,
  classMap,
  loading,
  bboxKey,
  showFacilities,
  showRecurrenceRing,
  recurrenceRadiusKm,
  basemap = 'muted',
  snapshot = false,
  sourceStatus,
}) {
  // The API validates coordinates, but map rendering is a safety boundary:
  // one malformed cached/proxied payload must not make Leaflet throw and take
  // down the whole operations screen. Null Island is excluded deliberately;
  // FIRMS never uses it as a meaningful fire location in this product.
  const safeEvents = useMemo(
    () =>
      events.filter((item) => {
        const lat = item?.event?.latitude
        const lon = item?.event?.longitude
        return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && !(lat === 0 && lon === 0)
      }),
    [events],
  )
  const safeFacilities = useMemo(
    () =>
      facilities.filter((facility) => {
        const { latitude: lat, longitude: lon } = facility ?? {}
        return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
      }),
    [facilities],
  )
  const [tileError, setTileError] = useState(false)
  const facilityIcon = useMemo(
    () =>
      L.divIcon({
        className: '',
        html: '<div class="facpin" style="width:9px;height:9px"></div>',
        iconSize: [9, 9],
        iconAnchor: [4.5, 4.5],
      }),
    [],
  )

  const selected = safeEvents.find((e) => e.event.event_id === selectedId)
  const tiles = BASEMAPS[basemap] ?? BASEMAPS.muted

  return (
    <div className="mapbox">
      <MapContainer
        center={INDIA}
        zoom={5}
        minZoom={3}
        maxZoom={17}
        scrollWheelZoom
        preferCanvas
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          key={basemap}
          url={tiles.url}
          attribution={tiles.attribution}
          maxZoom={tiles.maxZoom}
          className={tiles.className}
          eventHandlers={{
            tileerror: () => setTileError(true),
            load: () => setTileError(false),
          }}
        />
        <ScaleControl position="bottomright" imperial={false} />

        <FitToQuery bboxKey={bboxKey} />
        <PanToSelection events={safeEvents} selectedId={selectedId} />

        {showFacilities &&
          safeFacilities.map((f) => (
            <Marker key={f.facility_id} position={[f.latitude, f.longitude]} icon={facilityIcon}>
              <Popup>
                <div className="pop-h">{f.name || f.category_label}</div>
                <div className="pop-r">{f.category_label}</div>
                <div className="pop-r mono">{coords(f.latitude, f.longitude)}</div>
                <div className="pop-r faint">
                  OpenStreetMap {f.osm_type}/{f.osm_id}
                </div>
              </Popup>
            </Marker>
          ))}

        {/* The ring is the exact circle the backend used to count repeat
            detections at this source, so the number in the panel and the
            geometry on the map describe the same thing. */}
        {selected && showRecurrenceRing && (
          <Circle
            center={[selected.event.latitude, selected.event.longitude]}
            radius={recurrenceRadiusKm * 1000}
            pathOptions={{
              color: '#1d4ed8',
              weight: 1.25,
              opacity: 0.7,
              fillColor: '#1d4ed8',
              fillOpacity: 0.04,
              dashArray: '4 4',
            }}
          >
            <Popup>
              <div className="pop-h">Recurrence radius</div>
              <div className="pop-r">
                Detections within {recurrenceRadiusKm} km of this point on <em>earlier</em> days
                count as the same thermal source.
              </div>
            </Popup>
          </Circle>
        )}

        {safeEvents.map((item) => {
          const cls = classMap[item.classification.label]
          const isSelected = item.event.event_id === selectedId
          const hasFrp = item.event.frp_mw !== null && item.event.frp_mw !== undefined
          const color = cls?.color ?? '#6b7280'
          return (
            <CircleMarker
              key={item.event.event_id}
              center={[item.event.latitude, item.event.longitude]}
              radius={radiusFor(item.event.frp_mw)}
              pathOptions={{
                color: isSelected ? '#14181d' : color,
                weight: isSelected ? 2.25 : 1,
                fillColor: color,
                // Hollow means the product reported no radiative power.
                fillOpacity: hasFrp ? 0.72 : 0.12,
              }}
              eventHandlers={{ click: () => onSelect(item.event.event_id) }}
            >
              <Popup>
                <div className="pop-h">
                  <span className="code" style={{ color }}>
                    {cls?.code ?? '—'}
                  </span>
                  {item.classification.label_display}
                </div>
                <div className="pop-r">
                  RF vote score {pct(item.classification.confidence)} ·{' '}
                  {item.priority.level.toLowerCase()} priority
                </div>
                <div className="pop-r">
                  FRP {hasFrp ? `${num(item.event.frp_mw)} MW` : 'not reported'} · facility{' '}
                  {km(item.evidence.distance_to_nearest_facility_km)}
                </div>
                <div className="pop-r faint mono">{item.event.event_id}</div>
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>

      {loading && (
        <div className="ovl mapbusy" role="status">
          <span className="spin" />
          Fetching live FIRMS data and geographic evidence...
        </div>
      )}

      {!loading && safeEvents.length === 0 && (
        <div className="ovl mapbusy" role="status">
          No mapped detections match this query. Adjust the area, date window, or filters.
        </div>
      )}

      {tileError && (
        <div className="ovl mapbusy" role="status">
          Basemap tiles are temporarily unavailable. Detection coordinates and controls remain active.
        </div>
      )}

      {snapshot && (
        <div className="ovl" style={{ top: 10, left: 10, padding: '4px 9px' }}>
          <span className="chip chip-hist">
            <span className="led" />
            {sourceStatus?.firms_status === 'unavailable' || sourceStatus?.firms_status === 'not_configured'
              ? 'Degraded: historical fallback'
              : 'Historical capture'}
          </span>
        </div>
      )}

      <div className="ovl legend">
        <div className="ovl-head">Likely source</div>
        <div className="ovl-body">
          {Object.values(classMap).map((c) => (
            <div className="leg-row" key={c.id}>
              <span className="swatch" style={{ background: c.color, borderRadius: '50%' }} />
              <span className="code" style={{ color: c.color }}>
                {c.code}
              </span>
              <span className="trunc">{c.label}</span>
            </div>
          ))}
          {showFacilities && (
            <>
              <div className="leg-rule" />
              <div className="leg-row">
                <span className="facpin" style={{ width: 9, height: 9 }} />
                Industrial facility · OSM
              </div>
            </>
          )}
          <div className="leg-rule" />
          <div className="leg-note">
            Disc area ∝ radiative power
            <br />
            Hollow disc = FRP not reported
            <br />
            Every marker is one real FIRMS record
          </div>
        </div>
      </div>
    </div>
  )
}

export { BASEMAPS }
