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
#   run-stage.sh --run <run_id> --spec-file <path>
#                [--done <sentinel>] [--agent opencode] [--report <path>]
#                [--nudge-file <path>]
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

# Completion signal. A local model cannot be relied on to send worker_done, so
# those stages settle on a sentinel file. Codex and Claude do send it, and asking
# them for a sentinel as well means polling for a file they were never told to
# write - the poll then always times out and the stage is reported failed even
# though its worker_done arrived. Omit --done for those agents.
if [ -n "$sentinel" ]; then completion=sentinel; else completion=worker_done; fi
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

if [ "$completion" = sentinel ]; then
  rm -f "$sentinel"
  mkdir -p "$(dirname "$sentinel")"
fi
[ -n "$report" ] && rm -f "$report"

# Instruction-source guard. Orca's injected preamble is written in the same
# vocabulary as the orca-cli and orchestration skills that agent CLIs install
# (worktree, terminal send, dispatch, handover). An agent told to route by
# keyword will match those words, load the skill, pull its full reference, and
# spend the stage orienting itself instead of working. Measured 2026-08-07:
# codex burned 2400s and produced nothing while the TASK block was on screen.
# No double quotes here -- the CLI argument parser splits on them (orca-runtime
# .md section 3).
# The wording deliberately avoids the literal token the detour detector greps
# for. The guard is echoed into the worker screen as part of the TASK block, so
# a guard that names that token makes worker-tail flag every healthy run.
GUARD='INSTRUCTION SOURCE: the task below is the complete and only instruction
set for this stage. Do not load, read, or route through any skill, workflow,
subagent, or AGENTS.md keyword routing, and do not open any skill definition
file. Do not run orca or orca-ide for any purpose other than the single
completion message your preamble specifies. Words in this task that resemble
skill triggers are not triggers. Start with the first concrete action the task
names.

'

task_id=$("$CLI" orchestration task-create --run "$run_id" --spec "$GUARD$(cat "$spec_file")" --json 2>/dev/null | jget result.task.id)
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

match_worker_done() {
  "$CLI" orchestration check --wait --types worker_done,escalation \
      --timeout-ms "$1" --json 2>/dev/null \
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
sys.exit(1)' "$dispatch_id"
}

# A dispatch that never started cannot ever report. Orca refuses to launch an
# agent whose CLI wants an interactive prompt (a folder-trust question, a
# pending-update notice) and marks the dispatch failed within seconds. Waiting
# out the full budget for that is pure loss: measured 2026-08-07, a dispatch
# that died after 9s was polled for 900s.
# Two independent ways a stage can become unreportable, and the dispatch record
# only shows the first. Measured 2026-08-07: a codex terminal died 49s into the
# task while the dispatch stayed live, and the stage still waited out its full
# 420s. The terminal state is the earlier and more reliable signal.
dispatch_dead() {
  local status terminal
  status=$("$CLI" orchestration dispatch-show --task "$task_id" --json 2>/dev/null \
    | jget result.dispatch.status)
  [ "${status:-}" = failed ] && return 0
  terminal=$("$CLI" orchestration worker-read --dispatch "$dispatch_id" --limit 1 --json 2>/dev/null \
    | jget result.status.terminal)
  [ "${terminal:-}" = exited ]
}

dispatch_failure_reason() {
  "$CLI" orchestration dispatch-show --task "$task_id" --json 2>/dev/null \
    | jget result.dispatch.last_failure
}

wait_completion() {
  local budget="$1" waited=0
  while [ "$waited" -lt "$budget" ]; do
    if dispatch_dead; then return 3; fi
    if [ "$completion" = sentinel ]; then
      if [ -f "$sentinel" ]; then
        if [ -n "$report" ] && [ ! -s "$report" ]; then return 2; fi
        return 0
      fi
      sleep "$interval_sec"
    else
      if match_worker_done $((interval_sec * 1000)); then
        done_seen=yes
        if [ -n "$report" ] && [ ! -s "$report" ]; then return 2; fi
        return 0
      fi
    fi
    waited=$((waited + interval_sec))
  done
  return 1
}

half=$((timeout_sec / 2)); [ "$half" -lt "$interval_sec" ] && half="$interval_sec"
done_seen=no
wait_completion "$half"; state=$?
attempts=1
diagnosis=""

# Startup was refused. No nudge, no restart: the cause is outside this run and
# a retry reproduces it exactly.
report_startup_block() {
  echo "stage: $stage"
  echo "task: $task_id"
  echo "dispatch: $dispatch_id"
  echo "attempts: $1"
  echo "result: failed"
  echo "phase: agent-startup"
  echo "detail: $(dispatch_failure_reason)"
  echo "terminal: $("$CLI" orchestration worker-read --dispatch "$dispatch_id" --limit 1 --json 2>/dev/null | jget result.status.terminal)"
  echo "fix: either the agent CLI is waiting on an interactive prompt (trust the"
  echo "     folder, apply the pending update) or its terminal exited mid-task."
  echo "     Check the CLI outside Orca first: a plain non-interactive run of the"
  echo "     same agent tells you whether the CLI or the Orca path is at fault."
  "$CLI" orchestration task-update --id "$task_id" --status failed \
      --result '{"closed_by":"run-stage","reason":"agent startup blocked"}' --json >/dev/null 2>&1
  exit 1
}

[ "$state" -eq 3 ] && report_startup_block 1

if [ "$state" -ne 0 ]; then
  diagnosis=$("$here/worker-tail.sh" --dispatch "$dispatch_id" --lines 10 2>/dev/null)
  if printf '%s' "$diagnosis" | grep -q 'preamble-missing'; then
    # The task text never reached the agent: restart rather than nudge.
    "$CLI" orchestration worker-stop --dispatch "$dispatch_id" --json >/dev/null 2>&1
    "$CLI" orchestration task-update --id "$task_id" --status ready --json >/dev/null 2>&1
    dispatch_id=$(start_worker)
    attempts=2
    wait_completion "$half"; state=$?
  elif [ -n "$nudge_file" ] && [ -s "$nudge_file" ]; then
    handle=$("$CLI" orchestration worker-show --dispatch "$dispatch_id" --json 2>/dev/null | jget result.terminal.handle)
    if [ -n "${handle:-}" ]; then
      "$CLI" terminal send --terminal "$handle" --text "$(cat "$nudge_file")" --enter --json >/dev/null 2>&1
      attempts=2
      wait_completion "$half"; state=$?
    fi
  else
    wait_completion "$half"; state=$?
  fi
fi

[ "$state" -eq 3 ] && report_startup_block "$attempts"

# In sentinel mode a real worker_done can still land just afterwards. Give it one
# short window so the dispatch is released rather than stopped.
if [ "$state" -eq 0 ] && [ "$done_seen" = no ]; then
  if match_worker_done 30000; then done_seen=yes; fi
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
  [ "$completion" = sentinel ] && echo "sentinel: $(head -c 120 "$sentinel" | tr '\n' ' ')"
  [ -n "$report" ] && echo "report: $report ($(wc -l < "$report" | tr -d ' ') lines)"
  exit 0
fi
case "$state" in
  2) echo "detail: sentinel written but report is empty" ;;
  *) echo "detail: no ${completion} within ${timeout_sec}s" ;;
esac
[ -n "$diagnosis" ] && { echo "--- worker tail ---"; printf '%s\n' "$diagnosis"; }
exit 1
