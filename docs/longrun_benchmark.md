# Longrun Benchmark Iterations

This repo includes a longrun loop for iterative tuning based on HTML failure snapshots.

## Script

Use:

```bash
uv run python scripts/longrun_iter.py --rounds 20
```

Key defaults:
- Input file: `failed_links_578_20260315212513.txt`
- Parallelism: `-p 16`
- Timeout: `-t 15`
- Trace HTML snapshots: `--trace-html`
- Output root: `benchmarks/`
- Prefix: `longrun-p16d15-opt`

## Outputs

Each run creates:

```
benchmarks/<prefix><opt>-<timestamp>/
  console.log
  time.txt
  output/
    download-report.json
    trace-html/
  analysis.json
  auto_tuning.json
  cleanup.txt
```

`cleanup.txt` records how many PDFs were deleted after each run to keep disk usage under control.

## Auto-Tuning Rules

Auto-tuning rules are stored as JSON and merged at runtime:

- Default path: `scihub_cli/config/auto_tuning.json`
- Override path: set `SCIHUB_AUTO_TUNING_PATH`

The longrun script sets:

```
SCIHUB_AUTO_TUNING_PATH=benchmarks/longrun-auto-tuning.json
```

This file is updated after each iteration and can be removed to reset tuning.
