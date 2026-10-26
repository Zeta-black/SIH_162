import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { IconPause, IconPlay } from './mapicons.jsx'

/**
 * The Past-data scrubber. Appears only in Past mode.
 *
 * Plays the selected range one day at a time, revealing detections as they were
 * observed. Day ticks are generated from the range the backend gave us, so the
 * axis can never show days the archive does not contain.
 *
 * Playback advances a day index rather than animating individual markers: the
 * expensive work is the map redraw, and stepping days keeps that to one redraw
 * per frame-interval instead of one per detection.
 */

const SPEEDS = [1, 2, 4]
// At 1x a day takes this long. Chosen so a 10-day range plays in ~9 s — long
// enough to narrate, short enough not to stall a 3-minute demo.
const MS_PER_DAY_AT_1X = 900

function dayList(from, to) {
  if (!from || !to) return []
  const days = []
  const cursor = new Date(`${from}T00:00:00Z`)
  const end = new Date(`${to}T00:00:00Z`)
  if (Number.isNaN(cursor.getTime()) || Number.isNaN(end.getTime())) return []
  while (cursor <= end && days.length < 400) {
    days.push(cursor.toISOString().slice(0, 10))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return days
}

function dayLabel(iso) {
  const when = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(when.getTime())) return iso
  return when.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' })
}

export default function Timeline({ range, dayIndex, onDayIndex, detectionsByDay }) {
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const frameRef = useRef(null)
  const lastStepRef = useRef(0)

  const days = useMemo(() => dayList(range?.from, range?.to), [range?.from, range?.to])
  const total = days.length

  // A new range resets playback rather than keeping a stale index.
  useEffect(() => {
    setPlaying(false)
    onDayIndex(total > 0 ? total - 1 : 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range?.id, total])

  const step = useCallback(
    (timestamp) => {
      if (!lastStepRef.current) lastStepRef.current = timestamp
      const elapsed = timestamp - lastStepRef.current
      if (elapsed >= MS_PER_DAY_AT_1X / speed) {
        lastStepRef.current = timestamp
        onDayIndex((current) => {
          if (current >= total - 1) {
            setPlaying(false)
            return current
          }
          return current + 1
        })
      }
      frameRef.current = requestAnimationFrame(step)
    },
    [speed, total, onDayIndex],
  )

  useEffect(() => {
    if (!playing) {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
      lastStepRef.current = 0
      return undefined
    }
    frameRef.current = requestAnimationFrame(step)
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [playing, step])

  if (total === 0) return null

  const current = Math.min(Math.max(dayIndex, 0), total - 1)
  const peak = Math.max(1, ...days.map((d) => detectionsByDay?.[d] ?? 0))

  const onPlay = () => {
    // Restarting from the end replays from the beginning rather than sitting
    // still, which is what someone pressing play expects.
    if (!playing && current >= total - 1) onDayIndex(0)
    setPlaying((value) => !value)
  }

  return (
    <div className="fc-panel fc-timeline" role="group" aria-label="Replay controls">
      <button
        type="button"
        className="fc-tl-play"
        onClick={onPlay}
        aria-label={playing ? 'Pause replay' : 'Play replay'}
      >
        {playing ? <IconPause width={15} height={15} /> : <IconPlay width={15} height={15} />}
      </button>

      <div className="fc-tl-track">
        {/* Day ticks, height proportional to that day's detection count. A
            reader can see where the activity sits before pressing play. */}
        <div className="fc-tl-bars" aria-hidden="true">
          {days.map((day, index) => {
            const count = detectionsByDay?.[day] ?? 0
            return (
              <span
                key={day}
                className={`fc-tl-bar${index <= current ? ' is-past' : ''}`}
                style={{ height: `${Math.max(8, (count / peak) * 100)}%` }}
              />
            )
          })}
        </div>

        <input
          type="range"
          className="fc-tl-range"
          min={0}
          max={total - 1}
          step={1}
          value={current}
          aria-label={`Day ${current + 1} of ${total}: ${dayLabel(days[current])}`}
          aria-valuetext={dayLabel(days[current])}
          onChange={(event) => {
            setPlaying(false)
            onDayIndex(Number(event.target.value))
          }}
        />
      </div>

      <div className="fc-tl-meta">
        <span className="fc-tl-day">{dayLabel(days[current])}</span>
        <span className="fc-tl-of">
          {current + 1}/{total}
        </span>
      </div>

      <div className="fc-tl-speeds" role="group" aria-label="Playback speed">
        {SPEEDS.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={speed === value}
            onClick={() => setSpeed(value)}
          >
            {value}&times;
          </button>
        ))}
      </div>
    </div>
  )
}
