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
