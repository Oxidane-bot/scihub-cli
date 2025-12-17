#!/usr/bin/env bash

set -euo pipefail

identifier="1706.03762"
keep_temp=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --identifier)
      identifier="${2:-}"
      shift 2
      ;;
    --keep-temp)
      keep_temp=1
      shift
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/integration_test.sh [--identifier <ID>] [--keep-temp]

Creates an isolated uv venv, installs the built wheel, verifies entrypoints,
then downloads one paper and validates the output PDF.

Defaults:
  --identifier 1706.03762  (arXiv: Attention Is All You Need; avoids Sci-Hub)
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$repo_root/pyproject.toml" ]]; then
  echo "Could not locate repo root from $repo_root" >&2
  exit 2
fi

tmp="$(mktemp -d -t scihub-cli-integration-XXXXXX)"

cleanup() {
  status=$?
  if [[ $keep_temp -eq 1 || $status -ne 0 ]]; then
    echo "Temp preserved: $tmp" >&2
    return "$status"
  fi
  rm -rf "$tmp"
  return "$status"
}
trap cleanup EXIT

dist_dir="$tmp/dist"
venv_dir="$tmp/venv"
home_dir="$tmp/home"
out_dir="$tmp/out"
input_file="$tmp/input.txt"
cli_log="$tmp/cli.log"

mkdir -p "$dist_dir" "$home_dir" "$out_dir"
printf '%s\n' "$identifier" > "$input_file"

echo "Repo: $repo_root"
echo "Temp: $tmp"

base_python=""
if [[ -x "$repo_root/.venv/bin/python" ]]; then
  base_python="$repo_root/.venv/bin/python"
elif base_python="$(uv python find 3.10 2>/dev/null)"; then
  :
elif base_python="$(uv python find 3.11 2>/dev/null)"; then
  :
elif base_python="$(uv python find 3.12 2>/dev/null)"; then
  :
else
  uv python install 3.10
  base_python="$(uv python find 3.10)"
fi

echo "Using Python: $base_python"

uv build --wheel --sdist --out-dir "$dist_dir" --clear "$repo_root"

wheel="$(ls -1 "$dist_dir"/*.whl | head -n 1)"
echo "Wheel: $wheel"

if unzip -l "$wheel" | grep -E -q "(__pycache__/|\\.pyc$|\\.pyo$)"; then
  echo "Wheel unexpectedly contains bytecode/cache files:" >&2
  unzip -l "$wheel" | grep -E "(__pycache__/|\\.pyc$|\\.pyo$)" >&2
  exit 1
fi

uv venv --python "$base_python" --clear "$venv_dir"

venv_python="$venv_dir/bin/python"
venv_bin="$venv_dir/bin"
if [[ ! -x "$venv_python" ]]; then
  echo "Expected venv python not found: $venv_python" >&2
  exit 1
fi

uv pip install --python "$venv_python" "$wheel"

scihub_cli="$venv_bin/scihub-cli"
if [[ ! -x "$scihub_cli" ]]; then
  echo "Expected entrypoint not found: $scihub_cli" >&2
  exit 1
fi

HOME="$home_dir" "$scihub_cli" --version
HOME="$home_dir" "$venv_python" -m scihub_cli --version
HOME="$home_dir" "$venv_python" -m scihub_cli.scihub_dl --version

usage_line="$(HOME="$home_dir" "$venv_python" -m scihub_cli --help | head -n 1)"
echo "$usage_line" | grep -q "usage: scihub-cli"

HOME="$home_dir" "$scihub_cli" "$input_file" -o "$out_dir" -t 30 -r 2 >"$cli_log" 2>&1

if grep -q "Finding working mirror" "$cli_log"; then
  echo "Unexpected Sci-Hub mirror probing occurred during non-DOI integration test." >&2
  echo "Log: $cli_log" >&2
  exit 1
fi

pdf="$(find "$out_dir" -maxdepth 1 -type f -name '*.pdf' -print -quit)"
if [[ -z "$pdf" ]]; then
  echo "No PDFs produced in $out_dir" >&2
  echo "Log: $cli_log" >&2
  exit 1
fi

header="$(head -c 4 "$pdf")"
if [[ "$header" != "%PDF" ]]; then
  echo "Downloaded file is not a valid PDF: $pdf (header=$header)" >&2
  echo "Log: $cli_log" >&2
  exit 1
fi

size="$(wc -c < "$pdf" | tr -d ' ')"
echo "OK: $(basename "$pdf") ($size bytes)"
