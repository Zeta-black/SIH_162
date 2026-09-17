# FIRETRACE model training report

Generated from `ml/data/dataset_manifest.json`, `ml/artifacts/metrics.json`,
`ml/artifacts/validation.json`, and the training pipeline on 16 September 2026.

| Item | Evidence |
|---|---|
| Model | RandomForestClassifier, FIRETRACE Random Forest v1.0.0 |
| Task | Reproduce the project's weak-supervision source-type policy for a FIRMS detection; not fire confirmation |
| Labelled detections | 3,514 |
| Training / validation / test | 2,279 / 0 / 1,235 (no separate validation holdout; cross-validation is performed on training rows) |
| Features | 48, shared by training and inference |
| Classes | 4: INDUSTRIAL_FIRE, GAS_FLARE_OR_INDUSTRIAL_HEAT, AGRICULTURAL_BURNING, NATURAL_FIRE |
| Split | GroupShuffleSplit by `region_id`, 25% test, seed 42; 11 regions |
| Hyperparameters | 300 trees; max depth 14; min leaf 3; min split 6; balanced_subsample weights; bootstrap/OOB; seed 42 |

## Labels and class balance

Labels are emitted by `app/services/labeling.py` from a documented policy using
facility proximity, recurrence, FRP and land cover. They are not field-verified
ground truth.

| Class | Rows |
|---|---:|
| Industrial fire | 72 |
| Gas flare or industrial heat | 2,534 |
| Agricultural burning | 237 |
| Natural fire | 671 |

## Constructed held-out evaluation

| Metric | Value |
|---|---:|
| Accuracy | 1.0000 |
| Balanced accuracy | 1.0000 |
| Macro F1 | 1.0000 |
| OOB score | 0.9991 |
| Training-row CV balanced accuracy | 0.9992 +/- 0.0010 |

Confusion matrix (rows actual, columns predicted; class ordering as above):

```text
181  0    0  0
0    998  0  0
0    0    8  0
0    0    0  48
```

## Interpretation and limitations

This is **not real-world fire-classification accuracy**. The test labels are
deterministic functions of features available to the model, causing label
circularity. A depth-3 tree (0.9972 balanced accuracy) and logistic regression
(1.0000) match the forest, so the forest has 0.0000 lift over the best baseline.
The industrial-fire test support is only 8. The split demonstrates spatial
separation, not temporal generalisation: train/test dates overlap for 48 days.

Use the figures only as evidence that the shipped model reproduces the stated
policy on held-out regions. Predictions require human verification.
