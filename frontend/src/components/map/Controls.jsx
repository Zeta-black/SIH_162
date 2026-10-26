import { useEffect, useMemo, useRef, useState } from 'react'
import {
  IconClose,
  IconDownload,
  IconInfo,
  IconLayers,
  IconMapPaper,
  IconRing,
  IconSatellite,
  IconSearch,
} from './mapicons.jsx'

/* Map controls that sit bottom-right, plus the command palette and the
 * "About this data" sheet.
 *
 * Google Maps puts its layer and basemap controls bottom-right and people find
 * them without being told. Following that convention is worth more than any
 * novel placement. */

// --------------------------------------------------------------- layers
const LAYER_DEFS = [
  { key: 'detections', label: 'Detections', hint: 'Individual thermal detections' },
  { key: 'persistent', label: 'Persistent sources', hint: 'Heat seen on several days' },
  { key: 'facilities', label: 'Facilities', hint: 'Mapped industrial features (OSM)' },
  { key: 'industrial', label: 'Industrial areas', hint: 'OSM landuse polygons' },
  { key: 'landcover', label: 'Land cover', hint: 'Surroundings, where available' },
]

export function LayersControl({ layers, onToggle, onDownload, layerAvailability }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const away = (event) => {
      if (ref.current && !ref.current.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  return (
    <div className="fc-ctl-wrap" ref={ref}>
      <button
        type="button"
        className="fc-mapbtn"
        aria-label="Layers"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <IconLayers width={16} height={16} />
      </button>

      {open && (
        <div className="fc-pop fc-layers" role="dialog" aria-label="Map layers">
          <p className="fc-pop-title">Layers</p>
          {LAYER_DEFS.map((layer) => {
            const available = layerAvailability?.[layer.key] !== false
            return (
              <label
                key={layer.key}
                className={`fc-layer${available ? '' : ' is-unavailable'}`}
                title={available ? layer.hint : 'Not available in this dataset'}
              >
                <input
                  type="checkbox"
                  checked={Boolean(layers[layer.key]) && available}
                  disabled={!available}
                  onChange={() => onToggle(layer.key)}
                />
                <span className="fc-layer-label">{layer.label}</span>
                {!available && <span className="fc-layer-na">unavailable</span>}
              </label>
            )
          })}

          <div className="fc-pop-sep" />
          <button type="button" className="fc-layer-action" onClick={onDownload}>
            <IconDownload width={14} height={14} />
            Download GIS data
          </button>
        </div>
      )}
    </div>
  )
}

// ----------------------------------------------------------- basemap type
export function MapTypeControl({ mapType, onChange, satelliteAvailable }) {
  return (
    <div className="fc-maptype" role="group" aria-label="Base map">
      <button
        type="button"
        aria-pressed={mapType === 'map'}
        onClick={() => onChange('map')}
        title="Map"
      >
        <IconMapPaper width={15} height={15} />
        <span>Map</span>
      </button>
      <button
        type="button"
        aria-pressed={mapType === 'satellite'}
        onClick={() => onChange('satellite')}
        disabled={!satelliteAvailable}
        title={satelliteAvailable ? 'Satellite' : 'Satellite imagery unavailable'}
      >
        <IconSatellite width={15} height={15} />
        <span>Satellite</span>
      </button>
    </div>
  )
}

// ------------------------------------------------------- command palette
/**
 * Ctrl/Cmd+K. Jump to a facility, switch surface, toggle a layer.
 *
 * Keyboard-first by design: this is the control a daily operator would actually
 * use, and it costs no screen space.
 */
export function CommandPalette({ open, onClose, commands, onRun, onSearch, searchResults }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(0)
      // Focus after paint, or the browser swallows it.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  useEffect(() => {
    if (query.trim().length >= 2) onSearch(query.trim())
  }, [query, onSearch])

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const matchedCommands = commands.filter(
      (command) => !needle || command.label.toLowerCase().includes(needle),
    )
    const sites = (searchResults ?? []).map((hit) => ({
      id: `site:${hit.id}`,
      label: hit.name,
      hint: hit.detail,
      group: 'Places',
      run: () => onRun({ kind: 'site', hit }),
    }))
    return [...matchedCommands, ...sites]
  }, [query, commands, searchResults, onRun])

  useEffect(() => setCursor(0), [rows.length])

  if (!open) return null

  const onKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((value) => Math.min(value + 1, rows.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((value) => Math.max(value - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      rows[cursor]?.run?.()
      onClose()
    } else if (event.key === 'Escape') {
      onClose()
    }
  }

  return (
    <>
      <div className="fc-scrim" onClick={onClose} />
      <div className="fc-palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="fc-palette-input">
          <IconSearch width={16} height={16} aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            placeholder="Search facilities or run a command"
            aria-label="Search facilities or run a command"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <kbd>Esc</kbd>
        </div>

        <div className="fc-palette-list" role="listbox">
          {rows.length === 0 ? (
            <p className="fc-pop-empty">No matches.</p>
          ) : (
            rows.map((row, index) => (
              <button
                key={row.id}
                type="button"
                role="option"
                aria-selected={index === cursor}
                className="fc-palette-row"
                onMouseEnter={() => setCursor(index)}
                onClick={() => {
                  row.run?.()
                  onClose()
                }}
              >
                <span className="fc-palette-label">{row.label}</span>
                {row.hint && <span className="fc-palette-hint">{row.hint}</span>}
                <span className="fc-palette-group">{row.group}</span>
              </button>
            ))
          )}
        </div>
      </div>
    </>
  )
}

// ------------------------------------------------------------ about data
/**
 * "About this data". One small popover, no national-coverage claims.
 * Every figure is read from the API rather than written here.
 */
export function AboutSheet({ open, onClose, about }) {
  if (!open) return null
  return (
    <>
      <div className="fc-scrim" onClick={onClose} />
      <div className="fc-sheet" role="dialog" aria-modal="true" aria-label="About this data">
        <header className="fc-sheet-head">
          <span className="fc-sheet-title">About this data</span>
          <button type="button" className="fc-iconbtn fc-iconbtn-sm" onClick={onClose} aria-label="Close">
            <IconClose width={14} height={14} />
          </button>
        </header>

        <div className="fc-sheet-body">
          <dl className="fc-kv">
            <dt>Facilities monitored</dt>
            <dd>{about?.facilities?.toLocaleString('en-IN') ?? '—'}</dd>
            <dt>Detections held</dt>
            <dd>{about?.detections?.toLocaleString('en-IN') ?? '—'}</dd>
            <dt>Date range held</dt>
            <dd>{about?.date_range ?? '—'}</dd>
            <dt>Regions covered</dt>
            <dd>{about?.regions ?? '—'}</dd>
            <dt>Model</dt>
            <dd>{about?.model_version ? `v${about.model_version} · ${about.n_features}f` : '—'}</dd>
          </dl>

          <p className="fc-sheet-note">
            Thermal detections come from <b>NASA FIRMS</b> (VIIRS and MODIS),
            published a few hours after the satellite pass. FIRETRACE shows the
            observation time, not the time of a fire.
          </p>
          <p className="fc-sheet-note">
            Industrial features and land use come from <b>OpenStreetMap</b>
            contributors (ODbL). Coverage is uneven, and a facility missing from
            OSM is missing here.
          </p>
          <p className="fc-sheet-note">
            <b>This is not a fire confirmation service.</b> It classifies thermal
            detections and reports how confident it is. Proximity to a facility is
            context, not proof of cause. Coverage is the regions listed above, not
            all of India.
          </p>

          {about?.proxy_checks?.length > 0 && (
            <>
              <p className="fc-pop-title" style={{ marginTop: 'var(--sp-4)' }}>
                Consistency checks (proxy, not ground truth)
              </p>
              <dl className="fc-kv">
                {about.proxy_checks.map((check) => (
                  <div key={check.name} style={{ display: 'contents' }}>
                    <dt>{check.name}</dt>
                    <dd>{check.result}</dd>
                  </div>
                ))}
              </dl>
              <p className="fc-sheet-note">
                {about.proxy_caveat ??
                  'These compare the classifier against map context, not against verified incident reports. They indicate consistency, not accuracy.'}
              </p>
            </>
          )}
        </div>
      </div>
    </>
  )
}

export function AboutButton({ onClick }) {
  return (
    <button type="button" className="fc-iconbtn" aria-label="About this data" onClick={onClick}>
      <IconInfo width={16} height={16} />
    </button>
  )
}

export { IconRing }
