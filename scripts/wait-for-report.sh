#!/usr/bin/env bash
# Poll for a local worker's sentinel file without spending model tokens.
#
# Usage:
#   wait-for-report.sh --done <sentinel> [--report <report>] \
#                      [--timeout-sec N] [--interval-sec N]
#
# Exit 0  sentinel appeared (and --report, when given, exists and is non-empty)
# Exit 1  timed out
# Exit 2  bad usage
#
# Prints one summary line only. The caller still has to read the report and
# validate its format; a sentinel alone never proves success.
set -euo pipefail

sentinel=""
report=""
timeout_sec=1800
interval_sec=10

while [ $# -gt 0 ]; do
  case "$1" in
    --done) sentinel="${2:-}"; shift 2 ;;
    --report) report="${2:-}"; shift 2 ;;
    --timeout-sec) timeout_sec="${2:-}"; shift 2 ;;
    --interval-sec) interval_sec="${2:-}"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "wait-for-report: unknown argument: $1" >&2
      exit 2 ;;
  esac
done

if [ -z "$sentinel" ]; then
  echo "wait-for-report: --done <sentinel> is required" >&2
  exit 2
fi

case "$timeout_sec$interval_sec" in
  *[!0-9]*) echo "wait-for-report: --timeout-sec/--interval-sec must be integers" >&2; exit 2 ;;
esac
[ "$interval_sec" -gt 0 ] || { echo "wait-for-report: --interval-sec must be > 0" >&2; exit 2; }

mkdir -p "$(dirname "$sentinel")"

waited=0
while [ "$waited" -lt "$timeout_sec" ]; do
  if [ -f "$sentinel" ]; then
    if [ -n "$report" ] && [ ! -s "$report" ]; then
      echo "state: sentinel-without-report"
      echo "sentinel: $sentinel"
      echo "report: $report (missing or empty)"
      echo "waited_sec: $waited"
      exit 1
    fi
    echo "state: ready"
    echo "sentinel: $sentinel"
    echo "sentinel_body: $(head -c 200 "$sentinel" | tr '\n' ' ')"
    [ -n "$report" ] && echo "report: $report ($(wc -l < "$report" | tr -d ' ') lines)"
    echo "waited_sec: $waited"
    exit 0
  fi
  sleep "$interval_sec"
  waited=$((waited + interval_sec))
done

echo "state: timeout"
echo "sentinel: $sentinel (absent)"
echo "waited_sec: $waited"
exit 1
