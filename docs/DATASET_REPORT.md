# FIRETRACE dataset report

Source of record: `ml/data/dataset_manifest.json` (dataset v1.0.0, built
2026-09-16T02:09:42Z) and `ml/artifacts/validation.json`.

| Dataset stage | Count |
|---|---:|
| Raw FIRMS detections considered | 10,822 |
| Duplicate detections removed | 18 |
| Clean unique detections | 10,804 |
| Labelled detections | 3,514 |
| Unknown / deliberately unlabelled | 7,290 |
| Training split | 2,279 |
| Validation holdout | 0 |
| Test split | 1,235 |

The raw total is calculated as labelled + unknown + duplicates removed. Unknown
does not mean negative: it means the weak-supervision policy declined to assign
a class. Unknown rows are excluded from training and evaluation.

## Labelled class distribution

| Class | Count |
|---|---:|
| INDUSTRIAL_FIRE | 72 |
| GAS_FLARE_OR_INDUSTRIAL_HEAT | 2,534 |
| AGRICULTURAL_BURNING | 237 |
| NATURAL_FIRE | 671 |

## Provenance and scope

Coordinates, timestamps, FRP, brightness and source confidence originate from
NASA FIRMS captures. Industrial and land-use context is sourced from
OpenStreetMap. The records are legitimate observations, but class labels are
policy-derived rather than verified incident outcomes. The offline operational
demo snapshot contains 716 real FIRMS detections and is visibly identified as a
historical frozen capture.
