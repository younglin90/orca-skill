#!/usr/bin/env bash
# Drive one worker stage end to end in a single tool call.
#
# The coordinator's context grows with every API call, and cache is re-read in
# full each time, so an eight-call polling loop costs far more than the tokens
# it prints. This script performs task-create, worker-start, sentinel polling,
# one diagnosis, one optional nudge, the worker_done grace window, task close
# and worker teardown, then prints a fixed ~10-line receipt.
#
# Usage:
#   run-stage.sh --run <run_id> --spec-file <path> --done <sentinel>
#                [--agent opencode] [--report <path>] [--nudge-file <path>]
#                [--timeout-sec 600] [--interval-sec 15] [--stage <label>]
#
# The spec is read from a file, never passed as an argument, so quotes and
# heredocs in the spec cannot reach the CLI argument parser.
#
# --timeout-sec must fit inside the caller's own command timeout. A coding
# harness typically caps a foreground shell command at ten minutes, so keep
# --timeout-sec under that or launch this script in the background. If the
# script is killed mid-flight the worker keeps running and a worker_done still
# completes the task; the receipt is what is lost, so re-check `task-list`.
#
# Exit 0  stage settled successfully (report present and non-empty when asked)
# Exit 1  stage failed or timed out; the receipt says which
# Exit 2  bad usage
set -uo pipefail

CLI=orca-ide
run_id="" spec_file="" sentinel="" report="" nudge_file="" stage="stage"
agent="opencode" timeout_sec=600 interval_sec=15

while [ $# -gt 0 ]; do
  case "$1" in
    --run) run_id="${2:-}"; shift 2 ;;
    --spec-file) spec_file="${2:-}"; shift 2 ;;
    --done) sentinel="${2:-}"; shift 2 ;;
    --report) report="${2:-}"; shift 2 ;;
    --nudge-file) nudge_file="${2:-}"; shift 2 ;;
    --agent) agent="${2:-}"; shift 2 ;;
    --stage) stage="${2:-}"; shift 2 ;;
    --timeout-sec) timeout_sec="${2:-}"; shift 2 ;;
    --interval-sec) interval_sec="${2:-}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "run-stage: unknown argument: $1" >&2; exit 2 ;;
  esac
done

check_required() {
  if [ -z "$2" ]; then
    echo "run-stage: $1 is required" >&2
    exit 2
  fi
}
check_required --run "$run_id"
check_required --spec-file "$spec_file"
check_required --done "$sentinel"
[ -s "$spec_file" ] || { echo "run-stage: spec file is missing or empty: $spec_file" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"

jget() { python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: sys.exit(1)
cur=d
for k in sys.argv[1].split("."):
    if not isinstance(cur,dict): sys.exit(1)
    cur=cur.get(k)
    if cur is None: sys.exit(1)
print(cur)' "$1" 2>/dev/null; }

rm -f "$sentinel"
mkdir -p "$(dirname "$sentinel")"
[ -n "$report" ] && rm -f "$report"

task_id=$("$CLI" orchestration task-create --run "$run_id" --spec "$(cat "$spec_file")" --json 2>/dev/null | jget result.task.id)
if [ -z "${task_id:-}" ]; then
  echo "stage: $stage"
  echo "result: failed"
  echo "phase: task-create"
  echo "detail: no task id returned; the spec probably broke the argument parser"
  exit 1
fi

start_worker() {
  "$CLI" orchestration worker-start --task "$task_id" --worktree current \
      --agent "$agent" --json 2>/dev/null | jget result.dispatchId
}

dispatch_id=$(start_worker)
if [ -z "${dispatch_id:-}" ]; then
  echo "stage: $stage"; echo "task: $task_id"
  echo "result: failed"; echo "phase: worker-start"
  exit 1
fi

wait_sentinel() {
  local budget="$1" waited=0
  while [ "$waited" -lt "$budget" ]; do
    if [ -f "$sentinel" ]; then
      if [ -n "$report" ] && [ ! -s "$report" ]; then return 2; fi
      return 0
    fi
    sleep "$interval_sec"
    waited=$((waited + interval_sec))
  done
  return 1
}

half=$((timeout_sec / 2)); [ "$half" -lt "$interval_sec" ] && half="$interval_sec"
wait_sentinel "$half"; state=$?
attempts=1
diagnosis=""

if [ "$state" -ne 0 ]; then
  diagnosis=$("$here/worker-tail.sh" --dispatch "$dispatch_id" --lines 10 2>/dev/null)
  if printf '%s' "$diagnosis" | grep -q 'preamble-missing'; then
    # The task text never reached the agent: restart rather than nudge.
    "$CLI" orchestration worker-stop --dispatch "$dispatch_id" --json >/dev/null 2>&1
    "$CLI" orchestration task-update --id "$task_id" --status ready --json >/dev/null 2>&1
    dispatch_id=$(start_worker)
    attempts=2
    wait_sentinel "$half"; state=$?
  elif [ -n "$nudge_file" ] && [ -s "$nudge_file" ]; then
    handle=$("$CLI" orchestration worker-show --dispatch "$dispatch_id" --json 2>/dev/null | jget result.terminal.handle)
    if [ -n "${handle:-}" ]; then
      "$CLI" terminal send --terminal "$handle" --text "$(cat "$nudge_file")" --enter --json >/dev/null 2>&1
      attempts=2
      wait_sentinel "$half"; state=$?
    fi
  else
    wait_sentinel "$half"; state=$?
  fi
fi

# A real worker_done can land just after the sentinel. Give it one short window
# so the dispatch can be released instead of stopped. The Run mailbox holds
# unread messages from earlier stages, so match on this dispatch id: a substring
# match on the type alone reports another stage's completion as this one's and
# leaves the task stuck in `dispatched`.
done_seen=no
if [ "$state" -eq 0 ]; then
  if "$CLI" orchestration check --wait --types worker_done,escalation \
        --timeout-ms 30000 --json 2>/dev/null \
      | python3 -c '
import json, sys
want = sys.argv[1]
try:
    messages = json.load(sys.stdin)["result"]["messages"]
except Exception:
    sys.exit(1)
for message in messages:
    if message.get("type") != "worker_done":
        continue
    try:
        payload = json.loads(message.get("payload") or "{}")
    except Exception:
        continue
    if payload.get("dispatchId") == want:
        sys.exit(0)
sys.exit(1)' "$dispatch_id"; then
    done_seen=yes
  fi
fi

if [ "$done_seen" = yes ]; then
  "$CLI" orchestration worker-release --dispatch "$dispatch_id" --json >/dev/null 2>&1
  teardown=released
else
  "$CLI" orchestration worker-stop --dispatch "$dispatch_id" --json >/dev/null 2>&1
  teardown=stopped
fi

if [ "$state" -eq 0 ]; then
  if [ "$done_seen" = no ]; then
    "$CLI" orchestration task-update --id "$task_id" --status completed \
        --result "{\"report\":\"$report\",\"closed_by\":\"coordinator\"}" --json >/dev/null 2>&1
  fi
  outcome=ok
else
  "$CLI" orchestration task-update --id "$task_id" --status failed \
      --result '{"closed_by":"coordinator","reason":"sentinel not produced"}' --json >/dev/null 2>&1
  outcome=failed
fi

echo "stage: $stage"
echo "task: $task_id"
echo "dispatch: $dispatch_id"
echo "attempts: $attempts"
echo "worker_done: $done_seen"
echo "teardown: $teardown"
echo "result: $outcome"
if [ "$outcome" = ok ]; then
  echo "sentinel: $(head -c 120 "$sentinel" | tr '\n' ' ')"
  [ -n "$report" ] && echo "report: $report ($(wc -l < "$report" | tr -d ' ') lines)"
  exit 0
fi
case "$state" in
  2) echo "detail: sentinel written but report is empty" ;;
  *) echo "detail: sentinel never appeared within ${timeout_sec}s" ;;
esac
[ -n "$diagnosis" ] && { echo "--- worker tail ---"; printf '%s\n' "$diagnosis"; }
exit 1
