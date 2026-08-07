#!/usr/bin/env bash
# Compact, low-token diagnosis of a worker terminal.
#
# `worker-read --json` returns a TUI screen dump: box-drawing borders, spinner
# frames, status bars, duplicated glyphs. Pasting that into the coordinator's
# context costs hundreds of tokens per look and it never leaves the context
# again. This filters it to the lines that carry information and classifies the
# one thing worth branching on: whether the TASK block was ever injected.
#
# Usage: worker-tail.sh --dispatch <dispatch_id> [--lines 10]
#
# First output line is a verdict token:
#   task-visible       TASK block on screen; the worker received its instructions
#   active-no-task     no TASK block, but the screen shows real activity. The
#                      preamble has most likely scrolled off. Do NOT restart.
#   preamble-missing   no TASK block and almost nothing on screen; the injection
#                      was lost and the stage should be restarted
#   unreadable         the terminal could not be read
set -uo pipefail

dispatch="" lines=10
while [ $# -gt 0 ]; do
  case "$1" in
    --dispatch) dispatch="${2:-}"; shift 2 ;;
    --lines) lines="${2:-}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "worker-tail: unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$dispatch" ] || { echo "worker-tail: --dispatch is required" >&2; exit 2; }

# Capture first: a failed read must still produce a verdict token, so the caller
# can branch on one line instead of on an exit code plus a raw error dump.
screen=$(orca-ide orchestration worker-read --dispatch "$dispatch" --limit 60 --json 2>/dev/null || true)

printf '%s' "$screen" | python3 -c '
import json, re, sys

try:
    data = json.load(sys.stdin)
    tail = (data["result"].get("terminal") or {}).get("tail") or []
except Exception:
    print("unreadable")
    sys.exit(0)

BORDER = re.compile(r"^[\s─-╿▀-▟⠀-⣿|+*_=-]*$")
NOISE = re.compile(
    r"ctrl\+[a-z]|esc interrupt|tab agents|Tip |OpenCode \d|Click to expand"
    r"|Context \d+% left|weekly \d+% left|/models|/move |/review"
)
SPINNER = re.compile(r"(W?[oO]{2}rr?kk?ii?nn?gg?|▣|⡆|⠿|⣿){2,}")

seen, keep = set(), []
for raw in tail:
    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)
    line = line.replace("┃", " ").replace("╹", " ")
    line = SPINNER.sub(" ", line)
    line = re.sub(r"\s+", " ", line).strip()
    if not line or BORDER.match(line) or NOISE.search(line):
        continue
    if len(line) < 3 or line in seen:
        continue
    seen.add(line)
    keep.append(line)

joined = " ".join(keep)
if "=== TASK ===" in joined:
    verdict = "task-visible"
elif len(keep) >= 8:
    # Plenty on screen but the TASK block has scrolled out of the buffer.
    # Restarting here would throw away work that is already in progress.
    verdict = "active-no-task"
else:
    verdict = "preamble-missing"
print(verdict)

n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
for line in keep[-n:]:
    print("  " + line[:160])
' "$lines"
