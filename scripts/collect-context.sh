#!/usr/bin/env bash
# collect-context.sh - snapshot repo state (status, diff-stat, file tree, symbol
# index) into <run_dir>/artifacts/ so downstream pipeline stages can read files
# directly instead of asking an LLM to re-derive this context.
#
# Usage: collect-context.sh <run_dir> [repo_root]
#   repo_root defaults to `git rev-parse --show-toplevel` from the cwd.
set -euo pipefail

LINE_CAP=5000

die() {
  echo "collect-context.sh: $1" >&2
  exit 1
}

# Resolve to an absolute path without requiring GNU realpath.
abspath() {
  local target=$1
  if [ -d "$target" ]; then
    (cd "$target" && pwd)
  else
    local dir base
    dir=$(dirname -- "$target")
    base=$(basename -- "$target")
    (cd "$dir" && printf '%s/%s\n' "$(pwd)" "$base")
  fi
}

# truncate_to_cap <src> <dst> <cap> <total_lines>
# Copies at most <cap> lines from src to dst, appending a truncation note if
# total_lines exceeds cap.
truncate_to_cap() {
  local src=$1 dst=$2 cap=$3 total=$4
  if [ "$total" -gt "$cap" ]; then
    head -n "$cap" "$src" > "$dst"
    printf '... [truncated: showing %s of %s lines]\n' "$cap" "$total" >> "$dst"
  else
    cp "$src" "$dst"
  fi
}

count_lines() {
  wc -l < "$1" | tr -d ' '
}

[ "$#" -ge 1 ] && [ "$#" -le 2 ] || die "usage: collect-context.sh <run_dir> [repo_root]"

run_dir=$1
repo_root=${2:-}

if [ -z "$repo_root" ]; then
  if ! repo_root=$(git rev-parse --show-toplevel 2>/dev/null); then
    die "no repo_root given and current directory is not inside a git repository"
  fi
else
  [ -d "$repo_root" ] || die "repo_root '$repo_root' is not a directory"
  git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || die "repo_root '$repo_root' is not a git repository"
fi

mkdir -p "$run_dir/artifacts" || die "failed to create $run_dir/artifacts"
artifacts_dir=$(abspath "$run_dir/artifacts")

git_status_file="$artifacts_dir/git-status.txt"
diff_stat_file="$artifacts_dir/diff-stat.txt"
repo_tree_file="$artifacts_dir/repo-tree.txt"
symbols_file="$artifacts_dir/symbols.txt"

work_tmp=$(mktemp -d)
trap 'rm -rf "$work_tmp"' EXIT

# --- git-status.txt ---------------------------------------------------------
git -C "$repo_root" status --porcelain=v1 -b > "$git_status_file"
status_total_lines=$(count_lines "$git_status_file")
if [ "$status_total_lines" -gt 0 ]; then
  changed_files=$((status_total_lines - 1))
else
  changed_files=0
fi
[ "$changed_files" -ge 0 ] || changed_files=0

# --- diff-stat.txt -----------------------------------------------------------
{
  echo "== git diff --stat (unstaged) =="
  git -C "$repo_root" diff --stat || true
  echo
  echo "== git diff --cached --stat (staged) =="
  git -C "$repo_root" diff --cached --stat || true
} > "$diff_stat_file"

# --- repo-tree.txt -----------------------------------------------------------
tree_raw="$work_tmp/tree-raw.txt"
: > "$tree_raw"
if command -v rg >/dev/null 2>&1; then
  (cd "$repo_root" && rg --files --hidden -g '!.git') > "$tree_raw" || true
fi
if [ ! -s "$tree_raw" ]; then
  if git -C "$repo_root" ls-files > "$tree_raw" 2>/dev/null && [ -s "$tree_raw" ]; then
    :
  else
    (cd "$repo_root" && find . -path './.git' -prune -o -type f -print | sed 's#^\./##') > "$tree_raw" || true
  fi
fi
tree_total_lines=$(count_lines "$tree_raw")
truncate_to_cap "$tree_raw" "$repo_tree_file" "$LINE_CAP" "$tree_total_lines"

# --- symbols.txt --------------------------------------------------------------
symbols_raw="$work_tmp/symbols-raw.txt"
: > "$symbols_raw"
if command -v ctags >/dev/null 2>&1; then
  (cd "$repo_root" && ctags -R -x --languages=-JavaScript --output-format=u-ctags -f - .) > "$symbols_raw" 2>/dev/null || true
fi
# Declaration keyword at line start or after indentation/qualifiers. A pattern
# anchored as '^[A-Za-z_].*(class|struct|...)' cannot match a keyword that is
# itself the first token of the line, so anchor on the keyword directly.
SYM_KW='^[[:space:]]*(template|class|struct|enum|union|namespace|typedef|using|def|function|fn|impl|trait|module|pub|export|public|private|protected|static|inline|constexpr|virtual|extern)[[:space:]]'
# C/C++-style function definition/declaration starting at column 0.
SYM_FN='^[A-Za-z_][A-Za-z0-9_:<>,*&[:space:]]*[[:space:]][A-Za-z_][A-Za-z0-9_]*[[:space:]]*\('
if [ ! -s "$symbols_raw" ]; then
  if command -v rg >/dev/null 2>&1; then
    (cd "$repo_root" && rg -n --no-heading -e "$SYM_KW" -e "$SYM_FN") > "$symbols_raw" 2>/dev/null || true
  else
    (cd "$repo_root" && grep -rnE -e "$SYM_KW" -e "$SYM_FN" \
      --exclude-dir=.git .) > "$symbols_raw" 2>/dev/null || true
  fi
fi
symbols_total_lines=$(count_lines "$symbols_raw")
truncate_to_cap "$symbols_raw" "$symbols_file" "$LINE_CAP" "$symbols_total_lines"

# --- summary -------------------------------------------------------------------
cat <<SUMMARY
collect-context: repo_root=$repo_root
changed files (git status): $changed_files
tracked+untracked files: $tree_total_lines
symbol index lines: $symbols_total_lines
artifacts:
  $git_status_file
  $diff_stat_file
  $repo_tree_file
  $symbols_file
SUMMARY

exit 0
