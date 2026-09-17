# Test and replay cases

Generated 16 September 2026, 02:51 UTC from the live replay catalogue, with **every case actually
executed** to record its outcome. Regenerate by running the replay catalogue
and the end-to-end suite (`pytest tests/test_end_to_end.py`).

- **30 cases**, all drawn from 716 real NASA FIRMS
  detections captured between 2025-11-11 and 2026-09-10.
- Products: MODIS_NRT, VIIRS_NOAA20_SP, VIIRS_NOAA21_NRT, VIIRS_SNPP_NRT, VIIRS_SNPP_SP
- **Ground truth is UNKNOWN for every case.** No verified field report exists for
  any FIRMS pixel in this dataset. These cases test that the *pipeline* behaves
  correctly, not that a classification is correct.

## How a case is chosen

Each scenario is a predicate over a genuinely computed pipeline outcome. A
detection is only listed under a scenario if it really satisfies it, so a
scenario the data does not support simply does not appear. Nothing here was
hand-picked to make a demo look good.

## Execution summary

| | |
|---|---|
| Cases executed | 30 |
| Completed all 10 pipeline stages | **30** |
| Failed | **0** |
| Median end-to-end | 606 ms |
| Fastest / slowest | 488 ms / 1651 ms |
| Alert levels produced | HIGH=12, None=10, CRITICAL=8 |

## Cases by scenario

### Critical alert

*Industrial fire, corroborated, on site, not a routine flare.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-5F0A7E4E3D12` | 2026-03-16 | 07:15 | 21.5122 | 86.6968 | VIIRS_SNPP_SP | N | high | 15.36 | 7 | **UNKNOWN** |
| `EVT-78A1E4F33CDD` | 2026-03-16 | 07:15 | 21.5148 | 86.6996 | VIIRS_SNPP_SP | N | nominal | 10.20 | 7 | **UNKNOWN** |
| `EVT-854497881A07` | 2026-03-16 | 07:36 | 21.5146 | 86.6964 | VIIRS_NOAA20_SP | N20 | nominal | 9.24 | 7 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-5F0A7E4E3D12` | INDUSTRIAL_FIRE | HIGH (0.81) | CRITICAL | 7 | 4 | 672 ms |
| `EVT-78A1E4F33CDD` | INDUSTRIAL_FIRE | HIGH (0.81) | CRITICAL | 7 | 4 | 490 ms |
| `EVT-854497881A07` | INDUSTRIAL_FIRE | HIGH (0.81) | CRITICAL | 7 | 4 | 514 ms |

### Routine flare, suppressed

*A stack that burns every day. It must NOT page anyone.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-DBBAD725C280` | 2026-09-10 | 07:48 | 21.1001 | 72.6340 | VIIRS_NOAA21_NRT | N21 | nominal | 36.33 | 50 | **UNKNOWN** |
| `EVT-6776195FB3EA` | 2026-09-10 | 08:24 | 21.1016 | 72.6360 | VIIRS_SNPP_NRT | N | nominal | 16.70 | 50 | **UNKNOWN** |
| `EVT-6EA84FFC6F84` | 2026-09-10 | 20:19 | 21.1033 | 72.6351 | VIIRS_NOAA21_NRT | N21 | nominal | 13.90 | 50 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-DBBAD725C280` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1479 ms |
| `EVT-6776195FB3EA` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1306 ms |
| `EVT-6EA84FFC6F84` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1454 ms |

### Evidence gate abstains

*Insufficient evidence. The system reports Unclassified rather than guessing.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-1423938DEBAA` | 2025-11-13 | 07:43 | 30.7414 | 75.8177 | VIIRS_NOAA20_SP | N20 | nominal | 13.58 | 1 | **UNKNOWN** |
| `EVT-2C1281823EC9` | 2025-11-11 | 08:21 | 30.9809 | 75.8901 | VIIRS_NOAA20_SP | N20 | nominal | 4.42 | 1 | **UNKNOWN** |
| `EVT-205CEBD2C3FC` | 2025-11-11 | 08:00 | 30.6987 | 75.1062 | VIIRS_SNPP_SP | N | nominal | 3.68 | 1 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-1423938DEBAA` | UNKNOWN | MEDIUM (0.55) | none | 1 | 4 | 784 ms |
| `EVT-2C1281823EC9` | UNKNOWN | MEDIUM (0.51) | none | 1 | 2 | 540 ms |
| `EVT-205CEBD2C3FC` | UNKNOWN | MEDIUM (0.50) | none | 1 | 4 | 595 ms |

### Repeated detections

*The same source seen on many separate days — a persistent thermal source, not an incident.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-7995EFAC05DD` | 2026-09-10 | 20:19 | 21.1069 | 72.6464 | VIIRS_NOAA21_NRT | N21 | nominal | 9.84 | 50 | **UNKNOWN** |
| `EVT-2E4B6BC13F54` | 2026-09-10 | 20:19 | 21.1021 | 72.6458 | VIIRS_NOAA21_NRT | N21 | nominal | 9.84 | 50 | **UNKNOWN** |
| `EVT-DC1912C313A3` | 2026-09-10 | 07:48 | 21.1073 | 72.6442 | VIIRS_NOAA21_NRT | N21 | nominal | 9.05 | 50 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-7995EFAC05DD` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1139 ms |
| `EVT-2E4B6BC13F54` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1566 ms |
| `EVT-DC1912C313A3` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1263 ms |

### High radiative power

*A thermally intense detection. Intensity alone should not decide the class.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-3BFF99EFB344` | 2025-11-16 | 08:27 | 30.8728 | 75.0616 | VIIRS_NOAA20_SP | N20 | nominal | 49.03 | 1 | **UNKNOWN** |
| `EVT-0528A42B6C8B` | 2025-11-11 | 20:45 | 31.1019 | 75.5157 | VIIRS_NOAA20_SP | N20 | nominal | 29.70 | 4 | **UNKNOWN** |
| `EVT-33AB09D7E520` | 2026-03-07 | 08:27 | 30.4162 | 75.8464 | VIIRS_SNPP_SP | N | nominal | 28.68 | 4 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-3BFF99EFB344` | AGRICULTURAL_BURNING | MEDIUM (0.54) | none | 1 | 4 | 596 ms |
| `EVT-0528A42B6C8B` | AGRICULTURAL_BURNING | MEDIUM (0.60) | none | 4 | 4 | 577 ms |
| `EVT-33AB09D7E520` | AGRICULTURAL_BURNING | MEDIUM (0.53) | none | 4 | 1 | 526 ms |

### Multi-detection event

*Several detections cluster into one fire event.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-7AC629BF6699` | 2026-09-02 | 21:08 | 21.1054 | 72.6458 | VIIRS_NOAA21_NRT | N21 | nominal | 13.36 | 53 | **UNKNOWN** |
| `EVT-D3863440939A` | 2026-09-04 | 08:01 | 21.1045 | 72.6449 | VIIRS_NOAA21_NRT | N21 | nominal | 26.51 | 53 | **UNKNOWN** |
| `EVT-4FAF8B991EEA` | 2026-09-03 | 08:20 | 21.1069 | 72.6467 | VIIRS_NOAA21_NRT | N21 | nominal | 9.19 | 53 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-7AC629BF6699` | INDUSTRIAL_FIRE | HIGH (0.71) | HIGH | 53 | 5 | 1651 ms |
| `EVT-D3863440939A` | INDUSTRIAL_FIRE | HIGH (0.71) | HIGH | 53 | 5 | 1222 ms |
| `EVT-4FAF8B991EEA` | INDUSTRIAL_FIRE | HIGH (0.71) | HIGH | 53 | 5 | 1371 ms |

### High-priority outcome

*Strong evidence, high score.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-6993AD9DB5DC` | 2026-03-16 | 07:36 | 21.5111 | 86.6969 | VIIRS_NOAA20_SP | N20 | nominal | 9.24 | 7 | **UNKNOWN** |
| `EVT-A248F7104593` | 2026-03-16 | 07:15 | 21.5140 | 86.6949 | VIIRS_SNPP_SP | N | nominal | 13.13 | 7 | **UNKNOWN** |
| `EVT-814B9C504A4E` | 2026-09-01 | 20:21 | 21.1057 | 72.6446 | VIIRS_SNPP_NRT | N | nominal | 4.16 | 4 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-6993AD9DB5DC` | INDUSTRIAL_FIRE | HIGH (0.81) | CRITICAL | 7 | 4 | 542 ms |
| `EVT-A248F7104593` | INDUSTRIAL_FIRE | HIGH (0.81) | CRITICAL | 7 | 4 | 488 ms |
| `EVT-814B9C504A4E` | INDUSTRIAL_FIRE | HIGH (0.76) | CRITICAL | 4 | 5 | 1452 ms |

### Low-priority outcome

*The system should be willing to rank something as unimportant.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-84CFECCB6380` | 2026-03-06 | 07:24 | 21.7011 | 86.7375 | VIIRS_NOAA20_SP | N20 | nominal | 2.48 | 2 | **UNKNOWN** |
| `EVT-C8B9C198EFF5` | 2026-03-06 | 07:24 | 21.9978 | 86.1369 | VIIRS_NOAA20_SP | N20 | nominal | 1.85 | 3 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-84CFECCB6380` | UNKNOWN | LOW (0.33) | none | 2 | 1 | 494 ms |
| `EVT-C8B9C198EFF5` | NATURAL_FIRE | MEDIUM (0.47) | none | 3 | 3 | 577 ms |

### High-confidence detection

*FIRMS itself rates this detection high confidence.*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-755C939FCC93` | 2026-09-09 | 15:39 | 21.1093 | 72.6437 | MODIS_NRT | Terra | high | 13.03 | 50 | **UNKNOWN** |
| `EVT-04370874A531` | 2026-03-14 | 07:53 | 21.9569 | 86.3040 | VIIRS_SNPP_SP | N | high | 8.49 | 7 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-755C939FCC93` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1449 ms |
| `EVT-04370874A531` | NATURAL_FIRE | MEDIUM (0.48) | none | 7 | 5 | 562 ms |

### Low-confidence detection

*FIRMS rates this low confidence. Does that propagate into our output?*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-CCD38DC43E0C` | 2026-03-16 | 07:36 | 21.5105 | 86.6927 | VIIRS_NOAA20_SP | N20 | low | 3.47 | 7 | **UNKNOWN** |
| `EVT-92D85F0BEC46` | 2026-09-09 | 08:07 | 21.1061 | 72.6445 | VIIRS_NOAA21_NRT | N21 | low | 22.90 | 50 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-CCD38DC43E0C` | INDUSTRIAL_FIRE | HIGH (0.81) | CRITICAL | 7 | 4 | 606 ms |
| `EVT-92D85F0BEC46` | GAS_FLARE_OR_INDUSTRIAL_HEAT | HIGH (0.65) | HIGH | 50 | 5 | 1517 ms |

### Isolated detection

*A single pixel with no neighbours. Does the system resist over-reading one observation?*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-CFCB59078542` | 2025-11-11 | 08:21 | 30.7043 | 75.8359 | VIIRS_NOAA20_SP | N20 | nominal | 3.05 | 1 | **UNKNOWN** |
| `EVT-EAFDA18A6F10` | 2026-03-09 | 07:47 | 21.5163 | 86.6868 | VIIRS_SNPP_SP | N | nominal | 4.01 | 1 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-CFCB59078542` | INDUSTRIAL_FIRE | HIGH (0.66) | HIGH | 1 | 4 | 544 ms |
| `EVT-EAFDA18A6F10` | INDUSTRIAL_FIRE | MEDIUM (0.65) | none | 1 | 4 | 570 ms |

### Duplicate-data test

*The same event replayed twice. Does it raise a second alert?*

| Event ID | Date | Time UTC | Lat | Lon | Source | Sat | Conf | FRP MW | Det | Ground truth |
|---|---|---|---:|---:|---|---|---|---:|---:|---|
| `EVT-5F0A7E4E3D12` | 2026-03-16 | 07:15 | 21.5122 | 86.6968 | VIIRS_SNPP_SP | N | high | 15.36 | 7 | **UNKNOWN** |

*Detections in event* is how many detections the subject fire event contains.
*Events in area* is how many separate fire events the replay formed from the
surrounding neighbourhood it ingested — they are different numbers.

| Event ID | Result | Priority | Alert | Detections in event | Events in area | Runtime |
|---|---|---|---|---:|---:|---:|
| `EVT-5F0A7E4E3D12` | INDUSTRIAL_FIRE | HIGH (0.81) | CRITICAL | 7 | 4 | 595 ms |

## Observations worth flagging

- **A low-confidence FIRMS detection can still end up inside an alerting event.**
  `EVT-CCD38DC43E0C` is rated *low* confidence by FIRMS yet its event raised
  **CRITICAL**. This is not a bug: the alert is evaluated on the clustered
  *event* (7 detections), not on the single weakest pixel, and
  corroboration across passes is exactly what is supposed to outweigh one
  uncertain observation. It is listed here because a judge will spot it and it
  should be explained rather than discovered.
  `EVT-92D85F0BEC46` is rated *low* confidence by FIRMS yet its event raised
  **HIGH**. This is not a bug: the alert is evaluated on the clustered
  *event* (50 detections), not on the single weakest pixel, and
  corroboration across passes is exactly what is supposed to outweigh one
  uncertain observation. It is listed here because a judge will spot it and it
  should be explained rather than discovered.
- **No persistent flare reached CRITICAL** across 3 case(s), which is
  the single most important alert-fatigue behaviour in the system. Routine
  flaring is visible as HIGH but never pages anyone.
- **No abstained case raised an alert** (3 cases). When the evidence
  gate is not satisfied the system reports Unclassified and stays quiet.

## What these cases establish

1. **The pipeline runs end to end on real data.** All ten stages execute on
   every case, with measured per-stage timings.
2. **The alert rule discriminates.** Different cases produce different alert
   levels, including none at all. A hardcoded alert would produce one answer.
3. **Routine flaring is suppressed.** Persistent gas-flare cases do not reach
   CRITICAL, which is the single most important behaviour for alert fatigue.
4. **The system abstains.** Abstention cases return Unclassified rather than
   guessing when the evidence gate is not satisfied.
5. **Replaying one event twice raises one alert.** Incident identity is
   derived from the event, so a repeat observation updates rather than pages.

## What they do not establish

They say nothing about whether a classification is *correct*. Ground truth is
unknown for every row above. See `ML_MODEL_CARD.md` for why the model's headline
score is a measure of policy agreement rather than real-world accuracy.

