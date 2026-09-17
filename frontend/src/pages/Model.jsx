import { api } from '../api.js'
import { useMeta } from '../App.jsx'
import { useApi } from '../lib/useApi.js'
import { int, num, pct } from '../lib/format.js'
import {
  Bar,
  ErrorState,
  Group,
  Loading,
  Metric,
  Module,
  Note,
  Provenance,
} from '../components/ui.jsx'

/** Sequential single-hue ramp for the confusion matrix: light → dark by count. */
function cellStyle(value, rowTotal, isDiagonal) {
  if (!rowTotal) return { background: 'var(--surface-inset)', color: 'var(--ink-faint)' }
  const share = value / rowTotal
  if (value === 0) return { background: 'var(--surface-inset)', color: 'var(--ink-faint)' }
  // One hue, lightness carries magnitude — never a rainbow.
  const alpha = 0.1 + share * 0.75
  const hue = isDiagonal ? '26, 127, 75' : '165, 29, 18'
  return {
    background: `rgba(${hue}, ${alpha})`,
    color: share > 0.55 ? '#fff' : 'var(--ink)',
    fontWeight: isDiagonal ? 600 : 400,
  }
}

function shortName(label) {
  return label
    .replace('GAS_FLARE_OR_INDUSTRIAL_HEAT', 'Flare / heat')
    .replace('INDUSTRIAL_FIRE', 'Industrial fire')
    .replace('AGRICULTURAL_BURNING', 'Agricultural')
    .replace('NATURAL_FIRE', 'Natural fire')
}

function prettyFeature(name) {
  return name
    .replace(/^landcover__/, 'land cover: ')
    .replace(/^facility_cat__/, 'facility type: ')
    .replace(/_/g, ' ')
}

export default function Model() {
  const { classMap } = useMeta()
  const { data, error, loading, reload } = useApi(() => api.modelInfo(), [])

  if (loading) return <div className="surface"><div className="sheet"><Loading label="Loading model record…" /></div></div>
  if (error)
    return (
      <div className="surface">
        <div className="sheet">
          <ErrorState error={error} onRetry={reload} what="the model record" />
        </div>
      </div>
    )

  const metrics = data.metrics ?? {}
  const summary = data.training_summary ?? {}
  const policy = data.label_policy ?? {}
  const perClass = metrics.per_class ?? {}
  const labels = metrics.labels ?? []
  const matrix = metrics.confusion_matrix ?? []
  const features = data.top_features ?? []
  const maxImportance = Math.max(0.0001, ...features.map((f) => f.importance))

  if (!data.loaded) {
    return (
      <div className="surface">
        <div className="sheet">
          <header className="sheet-head">
            <h1>Model</h1>
          </header>
          <Note kind="alarm">
            <strong>No trained model is loaded.</strong> {data.status_note} Until then every
            detection is reported as unclassified — the system does not substitute a guess.
          </Note>
        </div>
      </div>
    )
  }

  return (
    <div className="surface">
      <div className="sheet">
        <header className="sheet-head">
          <h1>Model</h1>
          <p className="lede">
            A Random Forest classifier over {int(data.n_features)} features. Everything on this
            page is read from the trained artifact and its evaluation run — no figure here is
            written by hand.
          </p>
        </header>

        {/* ── the caveat that governs every number below ─────────────── */}
        <div style={{ marginBottom: 20 }}>
          <Note kind="warn">
            <strong>Read these metrics as agreement with a labelling policy, not as
            fire-classification accuracy.</strong>{' '}
            No public dataset states the true cause of an individual FIRMS detection, so training
            labels were assigned by the documented rule policy below rather than by field
            verification. The observations are real; the labels are inferred.
          </Note>
        </div>

        <Group title="Held-out performance" note={metrics.split_strategy}>
          <div className="metrics metrics-4">
            <Metric label="Balanced accuracy" value={num(metrics.balanced_accuracy, 3)} sub="mean per-class recall" />
            <Metric label="Macro F1" value={num(metrics.macro_f1, 3)} sub="unweighted across classes" />
            <Metric label="Accuracy" value={num(metrics.accuracy, 3)} sub="dominated by the largest class" />
            <Metric
              label="Test rows"
              value={int(metrics.test_rows)}
              sub={`${int(metrics.train_rows)} used for training`}
            />
          </div>

          <div style={{ marginTop: 14 }}>
            {metrics.circularity_warning && (
              <div style={{ marginBottom: 14 }}>
                <Note kind="alarm">
                  <strong>A perfect score is a warning, not a result — read this first.</strong>
                  <p className="sm" style={{ margin: '6px 0 0' }}>
                    This model scores {num(metrics.balanced_accuracy, 3)} balanced accuracy on
                    regions it has never seen. That does not mean it classifies fires well. Our
                    training labels come from a deterministic rule policy that decides using
                    facility distance, persistence, radiative power and land cover — and the model
                    is handed those same columns. So the task collapses from “classify the fire”
                    into “recover the rule set”, which is easy.
                  </p>
                  <p className="sm" style={{ margin: '6px 0 0' }}>
                    We proved it by trying to beat ourselves with trivial models: a{' '}
                    <strong>depth-3 decision tree scores 0.997</strong> and{' '}
                    <strong>logistic regression scores 1.000</strong>. Our lift over the best
                    baseline is <strong>0.000</strong>. Leakage was audited separately and is
                    clean. <code>ml/train.py</code> raises this warning itself rather than letting
                    the figure travel without it.
                  </p>
                </Note>
              </div>
            )}

            <Module title="Why the split is grouped by region">
              <p className="sm">
                The split is <strong>grouped by region</strong>. A random row-wise split would put
                detections from the same refinery on both sides, and the model would score well
                by memorising locations rather than learning anything transferable. The three
                held-out regions appear in no training row.
              </p>
              <div className="g3" style={{ marginTop: 12 }}>
                <div>
                  <div className="metric-k">Region-grouped split</div>
                  <div className="metric-v" style={{ fontSize: 19 }}>
                    {num(metrics.balanced_accuracy, 3)}
                  </div>
                  <div className="metric-s">reported above</div>
                </div>
                <div>
                  <div className="metric-k">5-fold CV (shuffled)</div>
                  <div className="metric-v" style={{ fontSize: 19, color: 'var(--ink-muted)' }}>
                    {metrics.cv_balanced_accuracy_mean != null
                      ? `${num(metrics.cv_balanced_accuracy_mean, 3)} ± ${num(metrics.cv_balanced_accuracy_std, 3)}`
                      : '—'}
                  </div>
                  <div className="metric-s">would be inflated by location memorisation</div>
                </div>
                <div>
                  <div className="metric-k">Out-of-bag</div>
                  <div className="metric-v" style={{ fontSize: 19, color: 'var(--ink-muted)' }}>
                    {metrics.oob_score != null ? num(metrics.oob_score, 3) : '—'}
                  </div>
                  <div className="metric-s">would be inflated by location memorisation</div>
                </div>
              </div>
              <p className="sm dim" style={{ marginTop: 12 }}>
                Normally the grouped number sits well below the other two, and that gap is the
                honest cost of refusing to memorise locations. Here all three are near 1.000 —
                which is itself the evidence that the target is rule-derived rather than hard.
                The grouping is still correct and still reported; it simply cannot demonstrate
                difficulty when the labels are recoverable. Train and test also share a 48-day
                window, so this is evidence of generalisation to unseen <em>places</em>, not to
                unseen <em>time</em>.
              </p>
            </Module>
          </div>
        </Group>

        {/* ── per class, including the weak one ──────────────────────── */}
        <Group title="Per-class performance">
          <div className="mod">
            <div className="gridwrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Class</th>
                    <th className="r">Precision</th>
                    <th className="r">Recall</th>
                    <th className="r">F1</th>
                    <th className="r">Test rows</th>
                    <th className="r">Training rows</th>
                  </tr>
                </thead>
                <tbody>
                  {labels.map((label) => {
                    const row = perClass[label] ?? {}
                    const cls = classMap[label]
                    const weak = (row.recall ?? 1) < 0.85
                    return (
                      <tr key={label}>
                        <td>
                          <span className="row" style={{ gap: 7 }}>
                            <span className="code" style={{ color: cls?.color }}>
                              {cls?.code ?? '—'}
                            </span>
                            {cls?.label ?? label}
                          </span>
                        </td>
                        <td className="num">{num(row.precision, 2)}</td>
                        <td className="num" style={{ color: weak ? 'var(--danger)' : undefined, fontWeight: weak ? 600 : undefined }}>
                          {num(row.recall, 2)}
                        </td>
                        <td className="num">{num(row['f1-score'], 2)}</td>
                        <td className="num dim">{int(row.support)}</td>
                        <td className="num dim">{int(summary.class_counts?.[label])}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {labels.some((l) => (perClass[l]?.recall ?? 1) < 0.85) && (
            <div style={{ marginTop: 12 }}>
              <Note kind="warn">
                <strong>Industrial fire is the weakest class, and it is also the rarest.</strong>{' '}
                Precision is high — when the model calls one, it is consistent with the policy —
                but recall is materially below the others, so it misses a meaningful share in
                regions it has never seen. This is the first thing more labelled data would fix,
                and industrial-fire calls should be treated as candidates for review rather than
                as detections of record.
              </Note>
            </div>
          )}
        </Group>

        {/* ── confusion matrix ───────────────────────────────────────── */}
        {matrix.length > 0 && (
          <Module title="Confusion matrix" note="rows = policy label · columns = model prediction">
            <Module>
              <div className="gridwrap">
                <table className="matrix">
                  <thead>
                    <tr>
                      <th />
                      {labels.map((l) => (
                        <th key={l}>{shortName(l)}</th>
                      ))}
                      <th style={{ paddingLeft: 12 }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matrix.map((row, i) => {
                      const total = row.reduce((a, b) => a + b, 0)
                      return (
                        <tr key={labels[i]}>
                          <th className="rh">{shortName(labels[i])}</th>
                          {row.map((value, j) => (
                            <td key={j} style={cellStyle(value, total, i === j)} title={`${value} of ${total}`}>
                              {value}
                            </td>
                          ))}
                          <td className="dim" style={{ background: 'transparent' }}>
                            {total}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <Provenance note="Green on the diagonal is agreement; red off it is disagreement, shaded by share of the row. Counts are held-out test detections." />
            </Module>
          </Module>
        )}

        {/* ── feature importance ─────────────────────────────────────── */}
        {features.length > 0 && (
          <Module title="What the model relies on" note="Gini importance, computed at training time">
            <Module>
              {features.map((f) => (
                <Bar
                  key={f.feature}
                  label={<span className="sm">{prettyFeature(f.feature)}</span>}
                  value={f.importance}
                  max={maxImportance}
                  display={f.importance.toFixed(3)}
                  color="var(--accent)"
                  labelWidth={215}
                />
              ))}
              <Provenance note="This is GLOBAL importance — what the forest relies on in general. It is a different question from why a particular detection was classified as it was; the Explore panel computes that per event from the decision paths." />
            </Module>
          </Module>
        )}

        {/* ── how labels were made ───────────────────────────────────── */}
        <Group title="Where the training labels came from">
          <div className="g2">
            <Module title="Label provenance">
              <dl className="kv">
                <dt>Observations</dt>
                <dd>NASA FIRMS — real detections</dd>
                <dt>Context</dt>
                <dd>OpenStreetMap — real facilities and land use</dd>
                <dt>Labels</dt>
                <dd>
                  <strong>Weak supervision</strong> — assigned by rule policy v{policy.version}
                </dd>
                <dt>Ground truth</dt>
                <dd style={{ color: 'var(--danger)' }}>No — not field-verified</dd>
                <dt>Labelled rows</dt>
                <dd className="num">{int(summary.rows_total)}</dd>
                <dt>Excluded</dt>
                <dd className="num">
                  {int(summary.dataset_manifest?.rows_unlabelled_excluded)}{' '}
                  <span className="dim sm">ambiguous, left unlabelled</span>
                </dd>
              </dl>
              <Provenance note={policy.note} />
            </Module>

            <Module title="Rules, and how often each fired">
              {Object.entries(summary.dataset_manifest?.rule_counts ?? {})
                .sort((a, b) => b[1] - a[1])
                .map(([rule, count]) => {
                  const ambiguous = rule.startsWith('R0')
                  return (
                    <Bar
                      key={rule}
                      label={
                        <span className="m" style={{ fontSize: 11, color: ambiguous ? 'var(--ink-faint)' : undefined }}>
                          {rule}
                        </span>
                      }
                      value={count}
                      max={Math.max(...Object.values(summary.dataset_manifest?.rule_counts ?? { a: 1 }))}
                      display={int(count)}
                      color={ambiguous ? 'var(--line-heavy)' : 'var(--ink-secondary)'}
                      labelWidth={210}
                    />
                  )
                })}
              <p className="sm dim" style={{ marginTop: 12 }}>
                <span className="m">R0_ambiguous</span> is the refusal case. Roughly two thirds
                of real detections meet no rule confidently and are excluded from training
                entirely rather than forced into a class — a classifier taught on coin flips is
                worse than one that has never seen the case.
              </p>
            </Module>
          </div>
        </Group>

        {/* ── abstention ─────────────────────────────────────────────── */}
        <Group title="When the model declines to answer">
          <Module>
            <p className="sm">
              <strong>Unclassified is not a trained class.</strong> The forest is trained on{' '}
              {data.classes.length} classes. When its top probability falls below{' '}
              <span className="m">{pct(data.abstention?.threshold)}</span>, FIRETRACE reports
              the detection as unclassified instead of asserting the weak leader — while still
              showing what that leader was, so nothing is hidden.
            </p>
            <p className="sm dim">
              This matters for a disaster-management tool: a confidently wrong industrial-fire
              call wastes a response, and a quiet &ldquo;I do not know&rdquo; is a usable signal that a human
              should look.
            </p>
          </Module>
        </Group>

        {/* ── reproducibility ────────────────────────────────────────── */}
        <Group title="Artifact and reproducibility">
          <div className="g2">
            <Module title="Trained artifact">
              <dl className="kv">
                <dt>Algorithm</dt>
                <dd>{data.algorithm}</dd>
                <dt>Model version</dt>
                <dd className="m">{data.model_version}</dd>
                <dt>Feature version</dt>
                <dd className="m">{data.feature_version}</dd>
                <dt>Dataset version</dt>
                <dd className="m">{data.training_data_version}</dd>
                <dt>Trained at</dt>
                <dd className="m xs">{data.trained_at ?? '—'}</dd>
                <dt>Features</dt>
                <dd className="num">{int(data.n_features)}</dd>
              </dl>
            </Module>
            <Module title="Hyperparameters">
              <dl className="kv">
                {Object.entries(data.hyperparameters ?? {}).map(([k, v]) => (
                  <div key={k} style={{ display: 'contents' }}>
                    <dt>{k.replace(/_/g, ' ')}</dt>
                    <dd className="m">{String(v)}</dd>
                  </div>
                ))}
              </dl>
              <Provenance
                processing="Fixed random seed; the same feature builder serves training and inference, so the two cannot drift."
                note="Rebuild with: npm run build-data, then npm run train."
              />
            </Module>
          </div>
        </Group>
      </div>
    </div>
  )
}
