#!/usr/bin/env python3
"""build-context-manifest.py - tracks which files an agent has already read
(and at what hash) so downstream pipeline stages can skip re-reading unchanged
files. Deterministic, stdlib-only, no network.

Usage:
  build-context-manifest.py <run_dir> add --path P --reason R --lines L --stage S [--repo-root ROOT]
  build-context-manifest.py <run_dir> list
  build-context-manifest.py <run_dir> check --path P [--repo-root ROOT]

Manifest file: <run_dir>/artifacts/context-manifest.json
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def die(message, code=2):
    print("build-context-manifest.py: {}".format(message), file=sys.stderr)
    sys.exit(code)


def resolve_repo_root(explicit_root):
    if explicit_root:
        return os.path.abspath(explicit_root)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if out:
                return os.path.abspath(out)
    except (OSError, FileNotFoundError):
        pass
    return os.getcwd()


def resolve_paths(path_arg, repo_root):
    abs_path = os.path.abspath(path_arg)
    rel_path = os.path.relpath(abs_path, repo_root)
    return rel_path, abs_path


def compute_hash(abs_path):
    if not os.path.isfile(abs_path):
        return "missing"
    hasher = hashlib.sha256()
    with open(abs_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def manifest_path_for(run_dir):
    return os.path.join(run_dir, "artifacts", "context-manifest.json")


def load_manifest(path):
    if not os.path.isfile(path):
        return {"entries": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        die("failed to read manifest '{}': {}".format(path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        die("manifest '{}' is malformed: expected {{'entries': [...]}}".format(path))
    return data


def save_manifest(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp_path, path)


def hash8(content_hash):
    if content_hash == "missing":
        return "missing"
    if ":" in content_hash:
        content_hash = content_hash.split(":", 1)[1]
    return content_hash[:8]


def cmd_add(args):
    mpath = manifest_path_for(args.run_dir)
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    data = load_manifest(mpath)

    repo_root = resolve_repo_root(args.repo_root)
    rel_path, abs_path = resolve_paths(args.path, repo_root)
    content_hash = compute_hash(abs_path)
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry = {
        "path": rel_path,
        "reason": args.reason,
        "required_lines": args.required_lines,
        "source_stage": args.source_stage,
        "content_hash": content_hash,
        "recorded_at": recorded_at,
    }

    entries = [e for e in data["entries"] if e.get("path") != rel_path]
    entries.append(entry)
    entries.sort(key=lambda e: e.get("path", ""))
    data["entries"] = entries

    save_manifest(mpath, data)
    print("recorded: {} ({})".format(rel_path, hash8(content_hash)))
    return 0


def cmd_list(args):
    mpath = manifest_path_for(args.run_dir)
    data = load_manifest(mpath)
    for entry in sorted(data["entries"], key=lambda e: e.get("path", "")):
        print(
            "{} — {} — {} — {}".format(
                entry.get("path", ""),
                entry.get("required_lines", ""),
                entry.get("source_stage", ""),
                hash8(entry.get("content_hash", "missing")),
            )
        )
    return 0


def cmd_check(args):
    mpath = manifest_path_for(args.run_dir)
    data = load_manifest(mpath)

    repo_root = resolve_repo_root(args.repo_root)
    rel_path, abs_path = resolve_paths(args.path, repo_root)
    current_hash = compute_hash(abs_path)

    for entry in data["entries"]:
        if entry.get("path") == rel_path:
            if entry.get("content_hash") == current_hash:
                print("unchanged: {}".format(rel_path))
                return 0
            print("changed: {}".format(rel_path))
            return 1

    print("new: {}".format(rel_path))
    return 1


def build_parser():
    parser = argparse.ArgumentParser(prog="build-context-manifest.py")
    parser.add_argument("run_dir", help="pipeline run directory (artifacts/ lives under it)")

    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="record or update a manifest entry")
    add_p.add_argument("--path", required=True)
    add_p.add_argument("--reason", required=True)
    add_p.add_argument("--lines", required=True, dest="required_lines")
    add_p.add_argument("--stage", required=True, dest="source_stage")
    add_p.add_argument("--repo-root")
    add_p.set_defaults(func=cmd_add)

    list_p = sub.add_parser("list", help="list manifest entries")
    list_p.set_defaults(func=cmd_list)

    check_p = sub.add_parser("check", help="check whether a path is already recorded and unchanged")
    check_p.add_argument("--path", required=True)
    check_p.add_argument("--repo-root")
    check_p.set_defaults(func=cmd_check)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
