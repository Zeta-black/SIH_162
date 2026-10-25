import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import MapApp from './MapApp.jsx'
import App from './App.jsx'

/**
 * Route table.
 *
 * `/` is the map. That is the product: one calm screen a first-time user can
 * read in seconds.
 *
 * `/analytics/*` keeps the seven analyst pages this project already had —
 * overview, alerts, the dense map workspace, replay, model card, source
 * provenance and the method writeup. None of that work was deleted; it was
 * demoted, because it is reference material rather than the front door.
 */
export default function Root() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<MapApp />} />
        <Route path="/analytics/*" element={<App />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  )
}
