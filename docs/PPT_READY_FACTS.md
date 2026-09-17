# FIRETRACE presentation facts — evidence controlled

Use only with the stated qualifiers. Sources are the dataset manifest, model
artifacts, replay service, and `PERFORMANCE_RESULTS.md`.

| Fact | Verified value |
|---|---|
| Observation source | NASA FIRMS active-fire / thermal-anomaly observations |
| Operational snapshot | 716 legitimate historical FIRMS detections |
| Labelled training dataset | 3,514 of 10,804 clean detections |
| Train / validation / test | 2,279 / 0 / 1,235 |
| Model / feature count / classes | Random Forest v1.0.0 / 48 / 4 |
| Constructed test accuracy, precision, recall, macro F1 | 1.000 / 1.000 / 1.000 / 1.000 |
| Meaning of those metrics | Policy-reproduction evaluation only; **not** real-world accuracy because labels are circular weak supervision and no per-detection ground truth exists |
| RF inference, batch | 0.3548 ms per row across 1,235 rows |
| Replay capability | Real historical source record is rerun through validation, features, ML, priority, alert policy and persistence |
| 10 / 100 / 1000-event platform benchmark | 311.8 ms / 1122.3 ms / 5780.9 ms median total; 0 failures |
| External notification | Dashboard ready; Telegram and email are not configured, and no delivery is claimed |

Suggested safe wording: “Current constructed test-set evaluation is 1.000;
it is not interpreted as real-world fire-classification accuracy because labels
are generated from a policy over model-visible features and verified ground
truth is unavailable.”
