#!/usr/bin/env python3
"""Static validation for the orca skill.

Usage: validate-skill.py [skill_dir]

Checks the structural invariants the skill depends on: frontmatter shape,
SKILL.md size budget, presence of every reference/script, the orca-ide-only CLI
rule, pipeline ordering, routing/budget rules, and duplicate-rule detection.
Exits 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

SKILL_MD_MAX_LINES = 250

REFERENCES = [
    "routing-policy.md",
    "wiki-contract.md",
    "agent-contracts.md",
    "token-policy.md",
    "review-policy.md",
    "orca-runtime.md",
]
SCRIPTS = [
    "collect-context.sh",
    "run-captured.sh",
    "summarize-log.sh",
    "build-context-manifest.py",
    "wait-for-report.sh",
    "run-stage.sh",
    "worker-tail.sh",
    "validate-skill.py",
]

# Marker -> the single file that is allowed to state the rule. Any other skill
# file repeating the marker is a duplicated rule.
CANONICAL_OWNER = {
    "orca-ide status --json": "references/orca-runtime.md",
    "worker-release": "references/orca-runtime.md",
    "pipeline-defaults.json": "references/wiki-contract.md",
    "LLM-Workspace/Runs": "references/wiki-contract.md",
    "content_hash": "references/token-policy.md",
    "codex_effort=auto": "references/routing-policy.md",
    "Planner correction": "references/review-policy.md",
    "report-file completion": "references/orca-runtime.md",
    "artifacts/done/<stage>.done": "references/orca-runtime.md",
}

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((bool(ok), name, detail))
    return bool(ok)


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return None, "SKILL.md does not start with '---'"
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return None, "unterminated frontmatter"
    try:
        import yaml  # type: ignore
    except ImportError:
        # Minimal fallback: only top-level "key:" lines are needed here.
        keys = re.findall(r"^([A-Za-z][A-Za-z0-9_-]*):", parts[1], re.M)
        return {k: True for k in keys}, "parsed without PyYAML (keys only)"
    try:
        return yaml.safe_load(parts[1]), ""
    except Exception as exc:  # noqa: BLE001 - report any YAML failure verbatim
        return None, f"invalid YAML: {exc}"


def main() -> int:
    skill_dir = os.path.abspath(
        sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..")
    )
    skill_md = os.path.join(skill_dir, "SKILL.md")

    if not os.path.isfile(skill_md):
        print(f"FAIL: no SKILL.md at {skill_md}")
        return 1

    text = read(skill_md)

    # 1. frontmatter
    fm, note = parse_frontmatter(text)
    check(fm is not None, "frontmatter parses", note)
    if fm:
        check(fm.get("name") == "orca", "name is orca", str(fm.get("name")))
        for key in ("description", "argument-hint", "allowed-tools"):
            check(key in fm, f"frontmatter has {key}")

    # 2. size budget
    n_lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    check(n_lines <= SKILL_MD_MAX_LINES, f"SKILL.md <= {SKILL_MD_MAX_LINES} lines", f"{n_lines} lines")

    # 3. files present
    skill_files = {"SKILL.md": text}
    for ref in REFERENCES:
        path = os.path.join(skill_dir, "references", ref)
        ok = os.path.isfile(path)
        check(ok, f"references/{ref} exists")
        if ok:
            skill_files[f"references/{ref}"] = read(path)
    for script in SCRIPTS:
        path = os.path.join(skill_dir, "scripts", script)
        ok = os.path.isfile(path)
        check(ok, f"scripts/{script} exists")
        if ok:
            check(os.access(path, os.X_OK), f"scripts/{script} is executable")

    # 4. every reference is pointed at from SKILL.md
    for ref in REFERENCES:
        check(f"references/{ref}" in text, f"SKILL.md points to references/{ref}")

    # 5. orca-ide only: no bare `orca <subcommand>` anywhere. Prose mentions of
    # the product name are fine; an invocation of a real subcommand is not.
    bare = re.compile(
        r"(?<![-\w])orca(?!-ide)(?![-\w])[ \t]+"
        r"(orchestration|status|terminal|worktree|skills|task-\w+|worker-\w+|"
        r"run-\w+|dispatch|gate-\w+|inbox|check|send|reply|ask|reset)\b"
    )
    for name, body in skill_files.items():
        hits = [
            f"{name}:{i}"
            for i, line in enumerate(body.splitlines(), 1)
            if bare.search(line)
        ]
        check(not hits, f"{name} uses orca-ide only", ", ".join(hits[:5]))

    all_text = "\n".join(skill_files.values())

    # 6. local scout runs before the Claude planner
    scout = text.find("S2 local scout")
    plan = text.find("S3 plan")
    check(
        0 < scout < plan,
        "local scout stage precedes plan stage",
        f"scout@{scout} plan@{plan}",
    )
    check(
        "Planner보다 **반드시 먼저** 실행" in text,
        "SKILL.md states scout-before-planner explicitly",
    )
    check("**Scope fence**" in text, "SKILL.md defines a scope fence")
    check(
        "active` 상태나 오래된 \"next\" 항목만으로 이어가지 않는다" in text,
        "active historical state alone cannot resume a Run",
    )

    # 7. low-risk local implementation gate
    routing = skill_files.get("references/routing-policy.md", "")
    check("Low-risk local implementation gate" in routing, "low-risk local gate documented")
    check(
        "Coordinator가 diff summary를 승인함" in routing,
        "local gate lists the diff-summary approval condition",
    )

    # 8. Claude must not sweep the whole repository
    contracts = skill_files.get("references/agent-contracts.md", "")
    check("저장소 전체 재탐색 금지" in contracts, "planner forbidden from full-repo re-scan")
    review = skill_files.get("references/review-policy.md", "")
    check(
        "전체 저장소나 raw artifacts를 자동으로 읽지 않는다" in review,
        "final review forbids auto-reading whole repo/raw artifacts",
    )
    check(
        "optional/deferred" in review and "out-of-scope historical follow-up" in review,
        "review separates required work from optional and historical follow-up",
    )
    check(
        "새 Task로 시작하지 않는다" in review,
        "review forbids starting unrelated follow-up before closure",
    )

    # 9. Codex must not read the whole wiki or raw logs
    check("전체 Wiki 읽기" in contracts and "전체 로그 읽기" in contracts,
          "coder forbidden from full-wiki / full-log reads")
    token = skill_files.get("references/token-policy.md", "")
    check(
        "raw 로그 전체를 직접 전달하지 않는다" in token,
        "raw logs are never handed to frontier models",
    )

    # 10. raw logs and full diff live in artifacts/
    wiki = skill_files.get("references/wiki-contract.md", "")
    check(
        "raw 로그, 전체 diff" in wiki and "artifacts/" in wiki,
        "raw logs and full diff routed to artifacts/",
    )
    check("full.diff" in wiki and "build.log" in wiki, "artifacts layout documented")

    # 11. exit-code preservation: execute the wrapper and compare, do not grep
    runcap = os.path.join(skill_dir, "scripts", "run-captured.sh")
    if os.path.isfile(runcap):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "probe.log")
            proc = subprocess.run(
                [runcap, "--log", log, "--label", "probe", "--",
                 "bash", "-c", "echo out; echo 'error: probe' >&2; exit 3"],
                capture_output=True, text=True,
            )
            check(proc.returncode == 3, "run-captured.sh preserves exit code",
                  f"got {proc.returncode}, want 3")
            body = read(log)
            check("out" in body and "error: probe" in body,
                  "run-captured.sh captures stdout+stderr into the artifact")
            check("out" not in proc.stdout.splitlines(),
                  "run-captured.sh does not echo full log to stdout")

            ok_log = os.path.join(tmp, "ok.log")
            # Output string must not appear in the argv, otherwise the summary's
            # own `cmd:` echo would look like leaked log content.
            proc_ok = subprocess.run(
                [runcap, "--log", ok_log, "--", "bash", "-c",
                 'a=QUIET; b=MARKER; echo "$a$b"'],
                capture_output=True, text=True,
            )
            check(proc_ok.returncode == 0, "run-captured.sh returns 0 on success",
                  f"got {proc_ok.returncode}")
            check("QUIETMARKER" in read(ok_log),
                  "run-captured.sh captures success output to the artifact")
            check("QUIETMARKER" not in proc_ok.stdout,
                  "run-captured.sh prints no log content on success")
    check("원래 exit code가 그대로 보존된다" in text, "SKILL.md states exit-code preservation")

    # 12. compression exclusion list
    for marker in ("code block", "허용오차", "acceptance criteria", "부정어"):
        check(marker in token, f"token-policy protects '{marker}' from compression")
    check("`ultra` 수준은 사용하지 않는다" in token, "ultra compression level disabled")

    # 13. correction budget
    for marker in ("Planner correction", "Codex correction", "OpenCode mechanical correction"):
        check(marker in review, f"correction budget lists {marker}")

    # 13.1 local worker completion contract
    runtime = skill_files.get("references/orca-runtime.md", "")
    check(
        "report-file completion" in runtime,
        "local worker completion contract documented",
    )
    check(
        "sentinel만 보고 성공으로 처리하지 않는다" in runtime,
        "sentinel alone never proves success",
    )
    check(
        "/mnt/c/" in runtime and "CommandNotFoundException" in runtime,
        "Windows-opencode/PowerShell precondition recorded",
    )
    check(
        "tools.task=false" in runtime,
        "subagent-tool precondition recorded",
    )
    check(
        "worker-stop` 다음에 `task-update" in runtime,
        "local completion states stop-then-close ordering",
    )
    check(
        "spec 본문에는 큰따옴표를 쓰지 않는다" in runtime,
        "spec quoting rule recorded",
    )
    check(
        "영구적으로 `retained`로 남는다" in runtime,
        "stopped dispatches stay retained (not a leak)",
    )
    check(
        "preamble이 유실될 수 있다" in runtime,
        "lost-preamble recovery recorded",
    )
    check(
        "검증되지 않은 주장이다" in runtime,
        "worker_done payload treated as unverified claim",
    )
    check(
        "cd <절대경로> && <명령>" in contracts,
        "spec must pin the working directory",
    )
    check(
        "sentinel 직후에 바로 stop하지 않는다" in runtime,
        "sentinel grace window before stopping the worker",
    )
    check(
        "선택 추출을 시키지 않는다" in contracts,
        "local workers are never asked to select-and-extract",
    )

    # 13.3 the failure model must match what was measured, not the old guess
    check(
        "단계 수는 상관없다" in contracts,
        "step-count theory retracted in favour of the measured cause",
    )
    check(
        "최대 3개" not in contracts,
        "the retracted three-step ceiling is gone",
    )
    check(
        "툴이 에러를 한 번 반환하면 회복하지 못한다" in contracts,
        "error-in-loop recorded as the real local failure mode",
    )
    check(
        "재시도시키지 않고 즉시 회수한다" in contracts,
        "recall-on-first-error rule present",
    )
    check(
        "문자열을 옮겨 적게 하지 않는다" in contracts,
        "local workers never retype fixed strings",
    )
    check(
        "kem/Project" in contracts and "LLM_Wiki" in contracts,
        "both observed path corruptions recorded",
    )
    check(
        "긴 경로를 명령의 인자로 넘기지 않는다" in contracts,
        "long paths are never passed as worker command arguments",
    )
    check(
        "인자 없는 러너 스크립트" in contracts,
        "argument-free runner script prescribed",
    )
    check(
        '[ "$ok" -gt 0 ]' in contracts,
        "report verdict requires a non-zero passed-check count",
    )
    check(
        "cd <worktree_root> && scripts/collect-context.sh" in text,
        "S1 pins the working directory before collecting context",
    )
    check(
        "finish_reason: length" in runtime and "limit.output" in runtime,
        "thinking-model output budget precondition recorded",
    )
    check(
        "tool_call 대신 평문" in runtime,
        "non-tool-calling model precondition recorded",
    )
    check(
        "에러 회복률로 고른다" in runtime,
        "worker model is selected on error recovery, not raw speed",
    )
    check(
        "온도가 통제되지 않은 비교로 모델을" in runtime,
        "model swaps require a controlled comparison",
    )
    check(
        "긴 문자열 재현 정확도를 측정한다" in runtime,
        "string-reproduction fidelity is a model precondition",
    )
    check(
        "두 경로, 접두사 겹침" in runtime,
        "prefix-overlap failure structure recorded with per-model numbers",
    )
    check(
        "OpenCode의 매처는 무죄다" in runtime,
        "edit failure attributed to reproduction, not the matcher",
    )

    # 13.4 the cost model that justifies one-call stages
    check(
        "횟수가 비용을 지배한다" in token,
        "token policy states round-trips dominate cost",
    )
    check(
        "run-stage.sh" in token and "run-stage.sh" in text,
        "one-call stage driver referenced from token policy and SKILL.md",
    )

    # 13.5 stage driver and tail filter behaviour: run them
    stage_sh = os.path.join(skill_dir, "scripts", "run-stage.sh")
    if os.path.isfile(stage_sh):
        proc = subprocess.run([stage_sh], capture_output=True, text=True)
        check(proc.returncode == 2, "run-stage.sh rejects missing arguments",
              f"got {proc.returncode}")
        check("--run is required" in proc.stderr,
              "run-stage.sh names the missing flag correctly", proc.stderr.strip()[:80])
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "spec.txt")
            open(empty, "w", encoding="utf-8").close()
            proc_spec = subprocess.run(
                [stage_sh, "--run", "run_x", "--spec-file", empty,
                 "--done", os.path.join(tmp, "s.done")],
                capture_output=True, text=True,
            )
            check(proc_spec.returncode == 2,
                  "run-stage.sh rejects an empty spec file",
                  f"got {proc_spec.returncode}")
        # The Run mailbox carries earlier stages' completions. Matching on the
        # message type alone credits this stage with another stage's worker_done.
        stage_src = read(stage_sh)
        check('grep -q \'"type": *"worker_done"\'' not in stage_src,
              "run-stage.sh does not match worker_done by type alone")
        check('payload.get("dispatchId") == want' in stage_src,
              "run-stage.sh scopes worker_done to its own dispatch")
        # Codex and Claude report by worker_done and never write a sentinel.
        # Demanding one made every such stage time out and report failed.
        check("completion=worker_done" in stage_src,
              "run-stage.sh supports a worker_done completion signal")
        check("check_required --done" not in stage_src,
              "--done is optional so worker_done agents are not forced to a sentinel")
        proc_nodone = subprocess.run(
            [stage_sh, "--run", "run_x", "--spec-file", "/etc/hostname"],
            capture_output=True, text=True,
        )
        check(proc_nodone.returncode != 2,
              "run-stage.sh accepts an invocation without --done",
              f"got {proc_nodone.returncode}")
    tail_sh = os.path.join(skill_dir, "scripts", "worker-tail.sh")
    if os.path.isfile(tail_sh):
        proc_tail = subprocess.run([tail_sh], capture_output=True, text=True)
        check(proc_tail.returncode == 2, "worker-tail.sh rejects missing arguments",
              f"got {proc_tail.returncode}")
        # No runtime needed: an unreadable stream must classify, not crash.
        proc_cls = subprocess.run(
            [tail_sh, "--dispatch", "ctx_definitely_not_a_real_dispatch"],
            capture_output=True, text=True,
        )
        check(proc_cls.returncode == 0 and proc_cls.stdout.strip().splitlines()[0]
              in {"unreadable", "preamble-missing", "active-no-task", "task-visible"},
              "worker-tail.sh always emits a verdict token",
              proc_cls.stdout.strip()[:60])
    check(
        "scripts/wait-for-report.sh" in text,
        "SKILL.md points to scripts/wait-for-report.sh",
    )
    check(
        "orca-runtime.md` §7" in contracts,
        "agent-contracts routes local completion to the runtime contract",
    )

    # 13.2 wait-for-report.sh behavior: run it, do not grep it
    waiter = os.path.join(skill_dir, "scripts", "wait-for-report.sh")
    if os.path.isfile(waiter):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.done")
            proc = subprocess.run(
                [waiter, "--done", missing, "--timeout-sec", "1", "--interval-sec", "1"],
                capture_output=True, text=True,
            )
            check(proc.returncode == 1, "wait-for-report.sh exits 1 on timeout",
                  f"got {proc.returncode}")
            check("state: timeout" in proc.stdout, "wait-for-report.sh reports timeout state")

            done = os.path.join(tmp, "ok.done")
            report = os.path.join(tmp, "ok.md")
            with open(done, "w", encoding="utf-8") as fh:
                fh.write("ok\n")
            with open(report, "w", encoding="utf-8") as fh:
                fh.write("build: pass\n")
            proc_ok = subprocess.run(
                [waiter, "--done", done, "--report", report,
                 "--timeout-sec", "5", "--interval-sec", "1"],
                capture_output=True, text=True,
            )
            check(proc_ok.returncode == 0, "wait-for-report.sh exits 0 when ready",
                  f"got {proc_ok.returncode}")
            check("state: ready" in proc_ok.stdout, "wait-for-report.sh reports ready state")

            empty = os.path.join(tmp, "empty.md")
            open(empty, "w", encoding="utf-8").close()
            proc_bad = subprocess.run(
                [waiter, "--done", done, "--report", empty,
                 "--timeout-sec", "5", "--interval-sec", "1"],
                capture_output=True, text=True,
            )
            check(proc_bad.returncode == 1,
                  "wait-for-report.sh fails on sentinel without report",
                  f"got {proc_bad.returncode}")

    # 14. invocation examples
    check(text.count("/orca") >= 3, "SKILL.md shows >= 3 invocation examples")
    check("economy=max" in text and "goal=" in text, "examples cover economy and goal args")

    # 15. duplicate-rule detection
    for marker, owner in CANONICAL_OWNER.items():
        offenders = [
            name
            for name, body in skill_files.items()
            if name != owner and marker in body
        ]
        check(not offenders, f"rule '{marker}' stated only in {owner}", ", ".join(offenders))

    # 16. syntax checks
    for script in SCRIPTS:
        path = os.path.join(skill_dir, "scripts", script)
        if not os.path.isfile(path):
            continue
        if script.endswith(".sh"):
            proc = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
            check(proc.returncode == 0, f"bash -n {script}", proc.stderr.strip()[:200])
        elif script.endswith(".py"):
            # ast.parse instead of py_compile: same syntax check, no __pycache__.
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read(),sys.argv[1])",
                 path],
                capture_output=True, text=True,
            )
            check(proc.returncode == 0, f"syntax check {script}", proc.stderr.strip()[:200])
    if _has("shellcheck"):
        for script in SCRIPTS:
            if not script.endswith(".sh"):
                continue
            path = os.path.join(skill_dir, "scripts", script)
            proc = subprocess.run(["shellcheck", "-S", "warning", path],
                                  capture_output=True, text=True)
            check(proc.returncode == 0, f"shellcheck {script}", proc.stdout.strip()[:400])
    else:
        results.append((True, "shellcheck", "not installed - skipped"))

    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"{mark}  {name}" + (f"  [{detail}]" if detail else ""))
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


def _has(binary: str) -> bool:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, binary)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
