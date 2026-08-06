#!/usr/bin/env bash
# run-captured.sh - run a command, capture its combined stdout+stderr to an
# artifact file, and print only a compact summary (never the raw log) unless
# the command failed, in which case a deterministic failure summary is
# appended via summarize-log.sh.
#
# Usage: run-captured.sh --log <artifact_path> [--label <text>] [--tail <n>] -- <command> [args...]
set -euo pipefail

die() {
  echo "run-captured.sh: $1" >&2
  exit 2
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
summarize_log="$script_dir/summarize-log.sh"

log_path=""
label=""
tail_n=40

while [ "$#" -gt 0 ]; do
  case "$1" in
    --log)
      [ "$#" -ge 2 ] || die "--log requires a value"
      log_path=$2
      shift 2
      ;;
    --label)
      [ "$#" -ge 2 ] || die "--label requires a value"
      label=$2
      shift 2
      ;;
    --tail)
      [ "$#" -ge 2 ] || die "--tail requires a value"
      tail_n=$2
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      die "unknown option '$1' (expected --log/--label/--tail before '--')"
      ;;
  esac
done

[ -n "$log_path" ] || die "--log <artifact_path> is required"
[ "$#" -ge 1 ] || die "no command given after '--'"

case "$tail_n" in
  ''|*[!0-9]*) die "--tail must be a non-negative integer" ;;
esac

cmd=("$@")

if [ -z "$label" ]; then
  label=$(basename -- "${cmd[0]}")
fi

log_dir=$(dirname -- "$log_path")
mkdir -p "$log_dir" || die "failed to create directory for log '$log_path'"

case "$log_path" in
  /*) abs_log=$log_path ;;
  *) abs_log="$(cd -- "$log_dir" && pwd)/$(basename -- "$log_path")" ;;
esac

start_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

{
  printf '# cmd:'
  printf ' %q' "${cmd[@]}"
  printf '\n'
  printf '# start: %s\n' "$start_time"
} > "$log_path"

# Execute the command directly as argv (no eval, no sh -c). Temporarily
# disable errexit so a non-zero exit code doesn't abort this script before we
# capture it.
set +e
"${cmd[@]}" >> "$log_path" 2>&1
exit_code=$?
set -e

lines=$(wc -l < "$log_path" | tr -d ' ')

printf 'label: %s\n' "$label"
printf 'cmd:'
printf ' %q' "${cmd[@]}"
printf '\n'
printf 'exit: %s\n' "$exit_code"
printf 'artifact: %s\n' "$abs_log"
printf 'lines: %s\n' "$lines"

if [ "$exit_code" -ne 0 ]; then
  "$summarize_log" "$log_path" "$tail_n"
fi

exit "$exit_code"
