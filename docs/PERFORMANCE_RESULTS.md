# Performance results

Measured 17 September 2026, 01:50 UTC by `python -m ml.benchmark --repeats 3`.
Every number below was produced by executing the pipeline on this machine.
Nothing here is estimated, extrapolated or copied from a previous run.

## Environment

| | |
|---|---|
| Os | Windows 11 (build 10.0.26200) |
| Machine | AMD64 |
| Processor | Intel64 Family 6 Model 158 Stepping 13, GenuineIntel |
| Logical Cpus | 8 |
| Total Memory | 15.9 GB |
| Python | 3.13.15 |
| Scikit Learn | 1.9.1 |
| Database | SQLite (single file, single process) |
| Detections available | 716 real FIRMS detections in the snapshot |

## What is measured

Enrichment (facility proximity, land cover, recurrence), feature extraction,
ML inference, priority scoring, clustering, alert-rule evaluation and the
database write.

**Excluded: NASA FIRMS and Overpass network time.** That is a third party's
latency, it varies with their load, and blending it into ours would produce a
number that describes neither. A cold live query is dominated by it.

## Results

Median of each stage across repeats.

| Events | Total | Per event | Enrich | Features | ML | Priority | Cluster | Alert | DB | Failures |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 155.4 ms | 15.536 ms | 22.6 | 0.3 | 121.1 | 0.7 | 1.3 | 0.0 | 2.5 | 0 |
| 100 | 434.3 ms | 4.343 ms | 265.9 | 1.9 | 112.0 | 4.9 | 30.8 | 0.1 | 5.2 | 0 |
| 1000 | 3063.0 ms | 3.063 ms | 2328.8 | 21.1 | 246.0 | 58.6 | 265.0 | 0.4 | 17.4 | 0 |

| Events | Fire events formed | Alerts raised | Peak RSS |
|---:|---:|---:|---:|
| 10 | 6 | 4 | 195 MB |
| 100 | 18 | 11 | 196 MB |
| 1000 | 390 | 23 | 203 MB |

## Honesty notes

- **Scales 1000 exceed the 716 real detections in the snapshot.**
  Rather than fabricate detections to fill the gap, the benchmark cycles
  through the real set. This is honest about throughput but it makes the
  *clustering* figure optimistic: repeated detections share coordinates, so
  they collapse into the same fire events instead of forming new ones. Treat
  the clustering column at those scales as a lower bound.
- Single process, single node, SQLite. There is no queue, no worker pool and
  no scheduled ingestion, so these figures describe one request on one machine.
- Timings use `perf_counter`, which is monotonic. Medians are reported rather
  than means so one slow run does not set the headline.
- The database figure is a local SQLite write. A networked PostGIS instance
  would be slower and is not measured here.

