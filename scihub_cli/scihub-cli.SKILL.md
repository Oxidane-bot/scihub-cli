---
name: scihub-cli
description: Download academic papers and optionally convert PDFs to Markdown using the installed scihub-cli command. Use when asked to retrieve papers from DOI, arXiv ID, PubMed/PMC ID, or academic URLs; batch-download literature; or prepare downloaded papers for local analysis. Prefer lawful open-access sources and respect access rights and publisher terms.
---

# SciHub CLI

Use `scihub-cli` to download papers from an input file containing one DOI, identifier, or URL per line.

## Workflow

1. Confirm that the requested material is available to the user and that downloading it complies with applicable access rights and terms.
2. Write the requested identifiers to a text file in the current project, one per line.
3. Run the CLI with an explicit output directory. Add `--email` when an Unpaywall email is available; do not place private email addresses in committed files.
4. Inspect the command exit code and `download-report.json` when it reports failures. State which identifiers succeeded and failed.

```bash
printf '%s\n' '10.1038/s41586-020-2649-2' > papers.txt
scihub-cli papers.txt --output papers --email you@example.org
```

## Common commands

```bash
# Convert successful PDFs to Markdown for local analysis
scihub-cli papers.txt --output papers --to-md --md-output papers/markdown

# Tune a large batch
scihub-cli papers.txt --output papers --parallel 4 --timeout 30 --retries 2

# See all downloader options
scihub-cli --help
```

Do not claim a paper was downloaded unless the command succeeded and the output file exists. When a source blocks access, report the failure and suggest an authorized or open-access route instead of attempting to bypass controls.
