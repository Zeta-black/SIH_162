// Class lookup built from /api/meta, so the frontend never hardcodes a colour,
// a code or a label. Changing the taxonomy on the backend changes every screen.

export function buildClassMap(meta) {
  const map = {}
  for (const cls of meta?.classes ?? []) map[cls.id] = cls
  return map
}

export function classOf(map, id) {
  return map[id] ?? null
}

/** Trained classes only — UNKNOWN is an abstention, not a predicted category. */
export function trainedClasses(meta) {
  return (meta?.classes ?? []).filter((c) => c.trained)
}
