#!/usr/bin/env python3
"""Report measured Codex worker token receipts for Orca task IDs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def default_sessions_root() -> Path:
    codex_home = os.environ.get("ORCA_CODEX_HOME") or os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "sessions"
    return Path.home() / ".local/share/orca/codex-runtime-home/home/sessions"


def message_text(payload: dict) -> str:
    if payload.get("type") != "message" or payload.get("role") != "user":
        return ""
    return "\n".join(
        item.get("text") or item.get("input_text") or ""
        for item in payload.get("content", [])
        if isinstance(item, dict)
    )


def inspect_session(path: Path, task_ids: set[str]) -> tuple[set[str], dict | None, str, int]:
    matched: set[str] = set()
    usage = None
    model = "unknown"
    tool_calls = 0
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = item.get("payload", {})
                if item.get("type") == "response_item":
                    text = message_text(payload)
                    if "You are a dispatched worker." in text:
                        matched.update(task for task in task_ids if task in text)
                    if payload.get("type") == "custom_tool_call":
                        tool_calls += 1
                elif item.get("type") == "turn_context" and model == "unknown":
                    model = payload.get("model") or model
                elif item.get("type") == "event_msg" and payload.get("type") == "token_count":
                    info = payload.get("info") or {}
                    usage = info.get("total_token_usage") or usage
    except OSError:
        return set(), None, model, tool_calls
    return matched, usage, model, tool_calls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions-root", type=Path, default=default_sessions_root())
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    wanted = set(args.task_id)
    found: dict[str, dict] = {}
    for path in args.sessions_root.rglob("*.jsonl"):
        matched, usage, model, tool_calls = inspect_session(path, wanted - found.keys())
        if not usage:
            continue
        for task_id in matched:
            record = dict(usage)
            record["uncached_input_tokens"] = max(
                0, record.get("input_tokens", 0) - record.get("cached_input_tokens", 0)
            )
            record.update(model=model, tool_calls=tool_calls, session=str(path))
            found[task_id] = record
        if found.keys() >= wanted:
            break

    missing = sorted(wanted - found.keys())
    ordered = [{"task_id": task, **found[task]} for task in args.task_id if task in found]
    totals = {
        key: sum(int(row.get(key, 0)) for row in ordered)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
            "tool_calls",
        )
    }
    result = {"tasks": ordered, "totals": totals, "missing": missing}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("| task | model | input | cached | uncached | output | total | tool calls |")
        print("|---|---|---:|---:|---:|---:|---:|---:|")
        for row in ordered:
            print(
                f"| {row['task_id']} | {row['model']} | {row.get('input_tokens', 0)} | "
                f"{row.get('cached_input_tokens', 0)} | {row['uncached_input_tokens']} | "
                f"{row.get('output_tokens', 0)} | {row.get('total_tokens', 0)} | "
                f"{row['tool_calls']} |"
            )
        print(
            f"| total | - | {totals['input_tokens']} | {totals['cached_input_tokens']} | "
            f"{totals['uncached_input_tokens']} | {totals['output_tokens']} | "
            f"{totals['total_tokens']} | {totals['tool_calls']} |"
        )
        if missing:
            print(f"missing: {', '.join(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
