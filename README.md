# orca — Claude Code Skill

Token-minimizing multi-agent development pipeline. Local OpenCode scouts, verifies,
and does chores; Codex implements; Claude only approves plans and reviews high-risk
changes. Every handoff is recorded in an Obsidian LLM Wiki so a run can be resumed
across sessions.

## Install

Clone directly into the personal skills directory:

```bash
git clone https://github.com/younglin90/orca-skill.git ~/.claude/skills/orca
```

Then in Claude Code:

```
/orca goal="fix the boundary-cell gradient bug and add a regression test"
```

## Requirements

The skill orchestrates external CLIs. Install these on every machine — cloning the
skill alone is not enough:

| Dependency | Notes |
|---|---|
| `orca-ide` | Orca CLI. Always this binary name. |
| `codex` | Default coder agent. |
| `opencode` | Default worker/scout agent. Needs a working provider + local model. |
| Obsidian vault | Any directory works. Default is `$REPO_ROOT/LLM-Wiki`. |

`worker=none` runs without OpenCode; verification falls back to deterministic
Coordinator tooling. `coder=claude` runs without Codex.

### OpenCode model note

A local model served with a small context window will stall every worker. Verify
the context length before a real run — the TUI footer shows the active model.

## Arguments

`key=value`, any order. Korean aliases are accepted for the role keys.

| Meaning | Keys | Values | Default |
|---|---|---|---|
| Planner | `planner`, `계획자` | claude\|codex\|opencode | claude |
| Coder | `coder`, `코더` | claude\|codex\|opencode | codex |
| Worker | `worker`, `janitor`, `잡일꾼` | claude\|codex\|opencode\|none | opencode |
| Wiki | `wiki`, `vault`, `위키` | absolute path | `$REPO_ROOT/LLM-Wiki` |
| Goal | `goal`, `objective`, `목적` | string (required) | — |
| Economy | `economy` | max\|balanced\|off | max |
| Caveman | `caveman` | off\|lite\|full | lite |

Model and effort overrides (`claude_model`, `claude_effort`, `codex_model`,
`codex_effort`, `opencode_model`, `opencode_variant`, `local_first`) are documented
in `SKILL.md` §1.

The current Claude session is always Coordinator and final Reviewer. That is not
configurable.

## Layout

```
SKILL.md                        entry point — arguments, stage flow
references/wiki-contract.md     wiki paths, run directories, document format
references/orca-runtime.md      Orca bootstrap, task creation, worker lifecycle
references/routing-policy.md    per-stage agent assignment, local implementation gate
references/token-policy.md      context budget, run reuse rules
references/review-policy.md     what Claude must review vs. delegate
references/agent-contracts.md   per-agent prompt contracts
scripts/                        context collection, log capture/summarize, validation
```

## Contributing across machines

Edit in place at `~/.claude/skills/orca`, commit, push. Other machines `git pull`.
Run `scripts/validate-skill.py` before committing.
