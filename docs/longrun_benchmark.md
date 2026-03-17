# Longrun Iteration Workflow

This repo does not use a built-in benchmark loop anymore.

Longrun work is an agent-driven iteration cycle:

1. Run the current code on a fixed input set.
2. Inspect success rate, failure modes, elapsed time, and HTML snapshots.
3. Modify code, config, or runtime parameters to improve outcomes.
4. Clean PDFs from the round output.
5. Continue to the next round by default unless blocked.

The goal is not to collect benchmark directories for their own sake. The goal is to finish a fixed number of rounds, explore changes that improve success rate and reduce time cost, then keep one best code version plus a summary report.

## Before Starting

Decide these values for the current longrun:

- Input file
- Target round count
- Output root under `benchmarks/`
- Baseline CLI options such as `-p`, `-t`, `-r`, `--trace-html`, `--fast-fail`, and CORE toggles
- Whether `SCIHUB_AUTO_TUNING_PATH` should point to a dedicated per-run JSON file

Always use `uv` to run the project.

Example round command template:

```bash
uv run python -m scihub_cli <input_file> -o <round_output_dir> --trace-html -p 16 -t 15
```

## Round Workflow

Each round should create a dedicated directory such as:

```text
benchmarks/<run_name>/round-01/
  console.log
  time.txt
  round-note.md
  output/
    download-report.json
    trace-html/
```

Recommended procedure for every round:

1. Run the current code against the same input file.
2. Save stdout and stderr to `console.log`.
3. Record elapsed wall time in `time.txt`.
4. Review `output/download-report.json`.
5. Review `output/trace-html/` for recurring 403, challenge, paywall, login, or broken candidate patterns.
6. Summarize the round in `round-note.md`.
7. Apply the next code, config, or parameter changes.
8. Delete PDFs generated in `output/`.
9. Start the next round by default.

Rounds are expected to continue automatically from the operator side. Stop only when there is a blocker, the current hypothesis needs manual validation, or the planned round count has been reached.

## Allowed Exploration

Between rounds, you may change anything that plausibly improves download success or total throughput, including:

- `auto_tuning` rules and host lists
- domain-specific User-Agent handling
- fast-fail, bypass, and recovery heuristics
- candidate ranking and source routing
- timeout, retry, deadline, and parallelism settings
- site-specific download handling
- diagnostics that make recurring failures easier to classify

Every change should be justified by the previous round's evidence. Avoid speculative churn that cannot be tied back to a concrete failure pattern or time sink.

## Required Artifacts

Keep these artifacts for each round:

- `console.log`
- `time.txt`
- `round-note.md`
- `output/download-report.json`
- `output/trace-html/`

Delete PDFs after each round to control disk usage. Only diagnostic artifacts should remain.

Each `round-note.md` should record at least:

- round number
- command used
- headline metrics such as total items, successes, failures, and elapsed time
- dominant failure patterns
- exact code, config, or parameter changes applied for the next round
- expected effect of those changes

## Best Version Selection

At the end of the planned rounds, choose one best version of the codebase and keep the working tree at that version.

Select the best version with this priority:

1. Higher download success count
2. Lower total runtime when success counts are tied
3. Smaller or lower-risk changes when results are effectively tied

The final deliverable should include:

- the repository left at the best version
- a longrun summary report covering each round
- the reason the final version was chosen
- unresolved failure clusters worth future work

## Notes On Auto-Tuning

`auto_tuning.json` rules loaded through `SCIHUB_AUTO_TUNING_PATH` are still a valid runtime input, but they are only one tool inside the longrun process.

If a run needs isolated rules, set:

```bash
SCIHUB_AUTO_TUNING_PATH=benchmarks/<run_name>/auto_tuning.json
```

Do not treat `auto_tuning.json` updates as the whole longrun workflow. Real longrun iteration may also require direct code changes.
