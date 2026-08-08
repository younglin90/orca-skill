---
name: orca
description: |
  Token-minimizing Orca multi-agent pipeline: local OpenCode scouts, verifies and
  does chores; Codex implements; the coordinating session only approves plans and
  reviews high-risk changes. Runs from Claude or from Codex. Handoffs recorded in
  an Obsidian LLM Wiki. For features, bug fixes, refactors, tests, build failures.
  Use for "orca", "다중 에이전트로 개발".
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - AskUserQuestion
---

# Orca Wiki Pipeline

Orca = 실행 권위, Obsidian LLM Wiki = 기록 권위, 로컬 모델 = 기본 실행자.
**이 Skill을 실행 중인 세션이 항상 Coordinator이자 최종 Reviewer다. 인수로 바꿀 수
없다.** Claude에서 돌든 Codex에서 돌든 같다. Coordinator 자신은 worker로 배정되지
않으며, 자기 자신을 dispatch 대상으로 삼지 않는다.
Orca CLI는 항상 `orca-ide`.

**이 파이프라인은 현재 워크트리 안에서만 돈다.** 새 워크트리, 새 repo, 새 Orca
project를 만들지 않는다. Coordinator와 모든 worker가 S0에서 고정한 워크트리 하나를
공유한다. 별도 격리 공간이 필요해 보이면 만들지 말고 사용자에게 묻고 중단한다. 고정
절차와 금지 인수 목록은 `orca-runtime.md` §2.1.

Codex 세션에서 이 Skill을 실행할 때는 한 가지가 더 필요하다. Codex의 전역
`developer_instructions`가 AGENTS.md 키워드 라우팅을 지시하고 있으면, 아래 절차에
나오는 worktree·terminal·dispatch 같은 단어가 `orca-cli`나 `orchestration` 스킬을
불러온다. **이 파일이 지시의 유일한 출처다. 다른 스킬을 로드하지 않는다.** 같은 이유로
worker에게도 instruction-source 가드를 넣는다 (`agent-contracts.md` §3).

## 0. 먼저: 신규인가 이어가기인가

Wiki 경로를 정한 뒤 (§1) 가장 최근 Run 디렉터리의 `99-state.md`를 본다. Run
디렉터리 위치는 `wiki-contract.md` §3.

- `overall_status`가 `completed`/`failed`이거나 Run이 없으면 **신규 실행**.
  §1부터 진행한다.
- 그렇지 않고 사용자가 같은 목표를 이어가는 중이며 남은 항목이 현재 목표에 속하면
  **이어가기**. `active` 상태나 오래된 "next" 항목만으로 이어가지 않는다.
  이때는 `99-state.md`와 `current_stage` reference **하나만** 읽고, 완료 단계는 건너뛴다.
- 목표가 바뀌었으면 이어가기가 아니다. 새 Run을 만든다 (`token-policy.md` §5).

## 1. 인수

`key=value`, 순서 고정 없음. 값의 바깥 따옴표는 제거한다.
최소 호출은 `goal=<objective>`, 선택 인수는 `planner`, `coder`, `worker`, `economy`,
`caveman`, `codex_effort`, `local_first`, `wiki`다.

| 의미 | 허용 키 | 값 | 기본값 |
|---|---|---|---|
| Planner | `planner`, `계획자` | claude\|codex\|opencode | claude |
| Coder | `coder`, `코더` | claude\|codex\|opencode | codex |
| Worker | `worker`, `janitor`, `잡일꾼` | claude\|codex\|opencode\|none | opencode |
| Wiki | `wiki`, `vault`, `위키` | 절대경로 | `$REPO_ROOT/LLM-Wiki` |
| Goal | `goal`, `objective`, `목적` | 문자열 (필수) | — |
| Economy | `economy` | max\|balanced\|off | max |
| Caveman | `caveman` | off\|lite\|full | lite |
| Claude model | `claude_model` | opus\|sonnet\|fable\|`<full-id>`\|inherit | inherit |
| Claude effort | `claude_effort` | low\|medium\|high\|xhigh\|max\|inherit | inherit |
| Codex model | `codex_model` | `<model-id>`\|default | default |
| Codex effort | `codex_effort` | low\|medium\|high\|xhigh\|auto | auto |
| OpenCode model | `opencode_model` | `<provider>/<model>`\|default | default |
| OpenCode variant | `opencode_variant` | provider별 effort 값\|default | default |
| Local first | `local_first` | true\|false | true |
| Worker 보존 | `keep_workers` | true\|false | false |

- 허용 agent ID는 `claude`, `codex`, `opencode` 뿐이다. 알 수 없는 값은 임의로
  대체하지 않는다. 허용 목록을 출력하고 중단한다.
- `none`은 Worker 키에만 허용. `worker=none`이면 검증 단계를 Coordinator가
  deterministic 도구로만 수행한다.
- `goal` 없으면 목적을 묻고 중단한다.
- `keep_workers=false`(기본)이면 worker terminal은 단계 종료 즉시 자동 종료된다
  (`orca-runtime.md` §3). Coordinator 세션은 어떤 값에서도 종료하지 않는다.
  `true`는 디버깅용으로 모든 worker terminal을 살려 둔다.
- 역할과 모델·effort에 조용한 기본값은 없다. 위 "기본값"은 첫 실행 질문의 권장
  선택지다. 질문·기억 절차는 `references/wiki-contract.md` §1–2, 실제 적용 방법은
  `references/orca-runtime.md` §3.
- `inherit`/`default`는 해당 CLI의 기존 설정을 그대로 쓴다는 뜻이다. OpenCode의
  provider와 로컬 모델은 이 Skill이 바꾸지 않는다.

확정 후 실행 전에 한 줄 확인 출력:
`planner=<a> coder=<a> worker=<a|none> economy=<m> claude=<model>/<effort>
codex=<model>/<effort> wiki=<abs> goal=<text>`

## 2. Reference 읽기 조건

필요한 단계에서만 읽는다. 미리 전부 읽지 않는다.

| 파일 | 읽는 시점 |
|---|---|
| `references/wiki-contract.md` | Wiki 경로·역할 결정, Run 디렉터리 생성, 문서 작성·갱신 |
| `references/orca-runtime.md` | Orca 부트스트랩, Task 생성, worker 시작·대기·release, 로컬 worker 완료 판정 |
| `references/routing-policy.md` | 단계별 실행자 배정, local implementation gate, codex_effort |
| `references/agent-contracts.md` | Task spec 작성, 산출물 형식 검사 |
| `references/token-policy.md` | 파일 읽기 판단, brief 생성, 로그 전달, 압축 수준 |
| `references/review-policy.md` | 최종 검토, correction 배정, 완료 판정 |

## 3. 파이프라인

```text
S0 부트스트랩 → S1 deterministic context → S2 local scout → S3 plan
→ S4 implement gate → S5 verify → S6 risk-based final review → S7 종료 sweep
```

**Scope fence** — S0와 S5 직후 모든 후속 항목을 `required`, `optional/deferred`,
`out-of-scope`로 분류한다. required만 dispatch한다. 현재 목표의 acceptance가 끝나면
새 bisect·조사·정리 작업을 시작하지 말고 S6→S7→최종 응답으로 즉시 닫는다.

**S0 부트스트랩** — `orca-runtime.md` §2로 runtime 상태 확인, live orchestration
guide 로드, Run 생성. 이어서 §2.1로 워크트리를 고정하고 그 id·path를 `00-run.md`에
기록한다. `wiki-contract.md` §1–3으로 Wiki 경로·역할
확정, Run 디렉터리 생성, `00-run.md`와 `99-state.md` 작성.

**S1 deterministic context** — LLM 없이 Coordinator가 직접:

```bash
cd <worktree_root> && scripts/collect-context.sh <run_dir>
```

`artifacts/`에 크기가 제한된 repo-tree·symbols 탐색 힌트와 git-status·diff-stat을
생성한다. 출력은 요약뿐이며 인덱스 전문을 model 입력으로 붙이지 않는다.
스크립트는 **cwd의 repo root**를 쓴다. worktree 기반 Run에서 cd를 빼면 메인 트리를
스캔하고 그 사실이 출력의 `repo_root=` 한 줄에만 나타난다. 그 줄을 확인한다.

**S2 local scout** — `worker` agent (기본 opencode)에게 Task 배정.
산출물 `10-context-pack.md` + `artifacts/context-manifest.json`.
형식은 `agent-contracts.md` §1. Planner보다 **반드시 먼저** 실행한다.
goal 기반 targeted `rg`만 허용하며 repo-tree·symbols 전문 읽기는 금지한다.
로컬 모델 worker는 lifecycle 메시지를 보내지 못한다. 완료 판정은
`orca-runtime.md` §7 (보고서 파일 + sentinel + Coordinator가 Task를 닫음).

**S3 plan** — Planner는 `10-context-pack.md`와 `99-state.md`만 읽고
`20-plan.md` 작성. 저장소 전체 재탐색 금지. `planner=claude`면 Coordinator가 직접
수행하고 별도 worker를 만들지 않는다. 이어서 OpenCode가 `20-plan.brief.md` 생성.
Coordinator가 계획을 승인한다.

**S4 implement gate** — `routing-policy.md` §5–6.

- `economy=max` + `local_first=true`: 저위험 작업이면 OpenCode가 먼저 구현.
  gate 8개 조건을 모두 통과하면 Codex를 호출하지 않는다.
- 그 외 또는 gate 실패: `30-coder-handoff.md` 작성 후 Coder(기본 codex) Task.
  Codex에는 brief·handoff·대상 line range·acceptance·금지 범위·테스트 명령·보고서
  경로만 전달한다 (`agent-contracts.md` §3).
- 산출물 `40-coder-report.md`. Codex Task 종료 후 terminal release
  (`orca-runtime.md` §3). 단, 즉시 S4 acceptance review와 1회 correction 가능성이
  있으면 같은 coder terminal을 그 review가 끝날 때까지만 유지한다.

**S5 verify** — `worker`가 `none`이 아니면 `50-worker-handoff.md` 작성 후 Worker
Task. 장시간 빌드·테스트·lint 실행은 먼저 인자 없는 deterministic runner 하나로
묶어 `scripts/run-captured.sh` 로그를 `artifacts/`에 남긴다. LLM worker는 실행 중
`ps`·`tail` polling을 하지 않고 완료된 receipt·요약과 targeted diff만 판정한다.
산출물 `60-worker-report.md`. 로컬 모델 worker면 S2와 같은 §7 완료 판정을 쓴다.
`worker=none`이면 Coordinator가 같은 deterministic 결과를 직접 판정한다.

**S6 final review** — `review-policy.md`. 고위험 변경만 정확한 diff 범위를 읽는다.
`90-final-review.md` 작성.

**S7 종료 sweep** — `orca-runtime.md` §5.1. 남은 worker terminal을 회수한 뒤에만
`99-state.md`를 completed/failed로 갱신한다. 사용자에게 보고하는 시점에 Coordinator
외의 agent terminal은 남아 있지 않아야 한다.

각 단계 종료 시 `99-state.md`와 `00-run.md` 진행표를 갱신한다. 단계별 worker는 그
단계가 끝나는 즉시 release 한다 (`orca-runtime.md` §3). 다음 단계 계획보다 release가
먼저다.

## 4. 명령 실행 규칙

빌드·테스트·lint 등 로그가 나오는 명령은 전부:

```bash
scripts/run-captured.sh --log <run_dir>/artifacts/build.log --label build -- <argv>
```

- 원래 exit code가 그대로 보존된다. 성공 시 로그 본문을 출력하지 않는다.
- **게이트나 빌드 명령을 파이프로 잇지 않는다.** `bash gate.sh | tail -20`의 exit
  status는 `tail`의 것이다. 실측 2026-08-07: 컴파일이 fatal error로 죽은 게이트가
  이 형태 때문에 exit 0으로 보고돼 통과로 오판할 뻔했다. exit code를 먼저 변수에
  받고 그 다음 로그를 본다.
- 실패 시 `scripts/summarize-log.sh`가 결정적 실패 줄만 뽑는다.
- deterministic 요약으로 부족할 때만 OpenCode가 raw log를 읽어 요약한다.
- Claude와 Codex에 raw 로그 전체를 전달하지 않는다.

파일을 읽기 전에는 `scripts/build-context-manifest.py <run_dir> check --path P`로
중복 읽기를 확인한다 (`token-policy.md` §1).

worker 단계 하나는 `scripts/run-stage.sh`로 **호출 1회**에 끝낸다. task 생성부터
teardown까지 그 안에서 일어나고 짧은 영수증만 돌아온다. 단계를 손으로 쪼개 여러 번
호출하면 그 왕복이 전부 Coordinator 컨텍스트에 영구히 쌓인다 (`token-policy.md` §0).
worker 화면 확인은 `scripts/worker-tail.sh`, sentinel만 따로 기다릴 때는
`scripts/wait-for-report.sh`. sleep/poll 루프를 직접 짜지 않는다.

**Token circuit breaker** — 역할별 model tool-call 상한은 Scout 10, Planner 6,
Coder 14, Verifier 12다. 한도를 넘기기 전에 명령을 batch runner로 합치거나 현재
증거로 bounded blocker를 기록한다. 장기 명령을 기다리기 위한 반복 `ps`, `tail`,
상태 조회는 호출 예산에 관계없이 금지한다. 세부 규칙과 실측 집계는
`references/token-policy.md` §0–§6.

## 5. 실패 처리

- worker `--outcome failed` 또는 `escalation`: correction budget 안에서 재배정.
  Planner 1회, Codex 1회, OpenCode 1회 (`review-policy.md` §3).
- **timeout + 산출물 0 + `worker-tail`이 `skill-detour`**: agent가 과제 대신 자기
  스킬을 로드한 것이다. spec이나 모델을 바꾸지 말고 instruction-source 가드부터
  확인한다 (`orca-runtime.md` §6). 가드가 있는데도 반복되면 그 agent를 그 단계에서
  빼고 Coordinator가 흡수한다.
- **worker가 고정 워크트리 밖에서 뜬 정황**(보고서 경로 불일치, 빈 `git status`,
  S1 `repo_root=` 불일치): 그 단계를 실패로 닫고 산출물을 옮겨 오지 않는다. selector를
  고쳐 고정 워크트리에서 다시 실행한다 (`orca-runtime.md` §2.1).
- 같은 실패 반복 시 추가 호출하지 않고 실패 정보를 기록하고 종료한다. 실패로 끝나는
  경우에도 S7 sweep은 건너뛰지 않는다. 실패한 worker terminal도 회수 대상이다.
- 한도 초과나 미충족 acceptance criteria는 성공으로 처리하지 않는다.
- worker timeout은 실패가 아니다. rolling wait를 계속한다.
- Orca runtime 상태 확인 실패는 즉시 중단 사유다 (`orca-runtime.md` §2).

## 6. 최종 사용자 보고

간결하게 다음만 출력한다.

```text
Goal / Planner / Coder / Worker / economy
완료 여부
주요 변경 (파일 단위)
빌드·테스트 결과 (exit code + artifact 경로)
Codex 호출 여부와 이유
남은 위험
Wiki Run 디렉터리 경로
[[90-final-review]] 위치
```

문서 전문을 사용자 응답에 붙여넣지 않는다. 경로와 요약만 보고한다.

## 7. 자체 검증

Skill 자체를 수정한 뒤에는 `scripts/validate-skill.py`를 실행한다.
