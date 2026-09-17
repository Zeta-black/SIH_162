// Line icons, drawn inline so there is no icon-font dependency and no network
// request. Deliberately plain: these are wayfinding marks, not decoration.

const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  viewBox: '0 0 20 20',
}

export const IconGauge = (p) => (
  <svg {...base} {...p}>
    <path d="M3 14a7 7 0 1 1 14 0" />
    <path d="M10 14l3.5-4" />
    <circle cx="10" cy="14" r="1" fill="currentColor" stroke="none" />
  </svg>
)

export const IconMap = (p) => (
  <svg {...base} {...p}>
    <path d="M2.5 5.5l5-2 5 2 5-2v11l-5 2-5-2-5 2z" />
    <path d="M7.5 3.5v11M12.5 5.5v11" />
  </svg>
)

export const IconModel = (p) => (
  <svg {...base} {...p}>
    <circle cx="10" cy="4" r="2" />
    <circle cx="4.5" cy="15" r="2" />
    <circle cx="15.5" cy="15" r="2" />
    <path d="M10 6v3M10 9L5.5 13M10 9l4.5 4" />
  </svg>
)

export const IconData = (p) => (
  <svg {...base} {...p}>
    <ellipse cx="10" cy="5" rx="6.5" ry="2.5" />
    <path d="M3.5 5v10c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5V5" />
    <path d="M3.5 10c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5" />
  </svg>
)

export const IconMethod = (p) => (
  <svg {...base} {...p}>
    <rect x="2.5" y="3" width="6" height="4.5" />
    <rect x="11.5" y="12.5" width="6" height="4.5" />
    <path d="M5.5 7.5v4a2 2 0 0 0 2 2h7" />
  </svg>
)

export const IconRefresh = (p) => (
  <svg {...base} {...p}>
    <path d="M16.5 8A6.5 6.5 0 0 0 5 5.5M3.5 12A6.5 6.5 0 0 0 15 14.5" />
    <path d="M16.5 3.5V8H12M3.5 16.5V12H8" />
  </svg>
)

export const IconDownload = (p) => (
  <svg {...base} {...p}>
    <path d="M10 3v9M6.5 9L10 12.5 13.5 9" />
    <path d="M3.5 14.5v2h13v-2" />
  </svg>
)

export const IconAlert = (p) => (
  <svg {...base} {...p}>
    <circle cx="10" cy="10" r="7.5" />
    <path d="M10 6.5v4.5M10 13.5v.3" />
  </svg>
)

export const IconFlame = (p) => (
  <svg viewBox="0 0 24 24" fill="currentColor" {...p}>
    <path d="M12 2c.5 3.2-1.2 4.6-2.7 6C7.6 9.6 6 11.2 6 14a6 6 0 0 0 12 0c0-2.3-1-3.7-2-5.2-.4 1-1 1.7-1.8 2 .6-3.3-.8-6.5-2.2-8.8Z" />
  </svg>
)

// Replay: a play triangle inside a cycle, for re-running a historical event.
export const IconReplay = (p) => (
  <svg {...base} {...p}>
    <path d="M16.5 10a6.5 6.5 0 1 1-2-4.7" />
    <path d="M16.5 3v3.2h-3.2" />
    <path d="M8.6 7.6l4 2.4-4 2.4z" fill="currentColor" stroke="none" />
  </svg>
)
