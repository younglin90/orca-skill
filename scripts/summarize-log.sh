#!/usr/bin/env bash
# summarize-log.sh - deterministic (non-LLM) pattern extraction over a captured
# log file: prints matching failure/error lines with line numbers and 2 lines
# of context, deduplicated, capped at max_lines.
#
# Usage: summarize-log.sh <log_path> [max_lines]   (max_lines default 40)
set -uo pipefail

usage() {
  echo "Usage: summarize-log.sh <log_path> [max_lines]" >&2
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  usage
  exit 2
fi

log_path=$1
max_lines=${2:-40}

case "$max_lines" in
  ''|*[!0-9]*)
    echo "summarize-log.sh: max_lines must be a non-negative integer" >&2
    exit 2
    ;;
esac

if [ ! -f "$log_path" ]; then
  echo "summarize-log.sh: log file not found: $log_path" >&2
  exit 2
fi

# Single alternation regex so a line matched by multiple patterns is still
# only reported once per pass (natural de-duplication).
pattern='FAIL|FAILED|ERROR|error:|fatal error|warning: .*\[-W|Assertion|assert|Traceback|Exception|undefined reference|ld returned|Segmentation fault|terminate called|panic|error\[E[0-9]+\]|\*\*\* Error|Test.*(FAILED|failed)'

tmp_out=$(mktemp)
trap 'rm -f "$tmp_out"' EXIT

if command -v rg >/dev/null 2>&1; then
  rg -n -A 2 --no-heading -e "$pattern" -- "$log_path" > "$tmp_out" 2>/dev/null
else
  grep -nE -A 2 -e "$pattern" -- "$log_path" > "$tmp_out" 2>/dev/null
fi
# Both rg and grep exit non-zero when there are no matches; that is an
# expected outcome here, not a script error, so don't let it trip anything.
true

if [ ! -s "$tmp_out" ]; then
  log_dir=$(dirname -- "$log_path")
  abs_log="$(cd -- "$log_dir" 2>/dev/null && pwd)/$(basename -- "$log_path")"
  echo "no deterministic failure pattern found; escalate log to local summarizer: $abs_log"
  exit 0
fi

total_lines=$(wc -l < "$tmp_out" | tr -d ' ')
if [ "$total_lines" -gt "$max_lines" ]; then
  head -n "$max_lines" "$tmp_out"
  echo "... [truncated: showing $max_lines of $total_lines matched-context lines]"
else
  cat "$tmp_out"
fi

exit 0
