# Wiki Contract

Obsidian LLM Wiki는 **기록 권위자**다. 계획, 명세, 결과, correction, 검토는
여기에 남는다. 실행 권위는 Orca에 있다 (`orca-runtime.md`).

## 1. Wiki 경로 결정

우선순위:

1. 호출 인수 `wiki` / `vault` / `위키`
2. 환경변수 `LLM_WIKI_ROOT`
3. `$REPO_ROOT/.llm-wiki-path` 첫 줄
4. 기본값 `$REPO_ROOT/LLM-Wiki`

`REPO_ROOT=$(git rev-parse --show-toplevel)`. 반드시 절대경로. 기본값 사용 시
디렉터리가 없으면 `mkdir -p`로 만들고 사용자에게 알린다. 저장소 밖이면 추측하지
말고 절대경로를 요청한 뒤 중단한다.

## 2. 역할 기억

파일: `<WIKI_ROOT>/LLM-Workspace/pipeline-defaults.json`

```json
{"planner":"claude","coder":"codex","worker":"opencode","economy":"max",
 "caveman":"lite","local_first":true,
 "claude_model":"inherit","claude_effort":"inherit",
 "codex_model":"default","codex_effort":"auto",
 "opencode_model":"default","opencode_variant":"default","updated_at":"<ISO8601>"}
```

키별 독립 결정: 인수(`explicit`) → 기억 파일(`remembered`) → 없으면 첫 실행이므로
`AskUserQuestion`으로 질문(`asked`). 확정 즉시 전체를 덮어써서 갱신한다.
기억은 Wiki 단위다.

질문 대상은 역할 3개 + Claude 조합 + Codex 조합이다. `AskUserQuestion` 한 번에
최대 4개까지만 담기므로 두 번에 나눠 묻고, 미정 항목만 묻는다.

1차 (역할):

- planner: `claude`(권장) / `codex` / `opencode`
- coder: `codex`(권장) / `opencode` / `claude`
- worker: `opencode`(권장) / `codex` / `none`

2차 (모델·생각 깊이):

- Claude worker: `inherit`(권장, 현재 CLI 설정 사용) / `opus + xhigh` /
  `sonnet + medium` / `opus + max`
- Codex: `default`(권장, 현재 CLI 설정 사용) / `default + effort auto` /
  `default + effort high` / `default + effort xhigh`

모델 ID를 추측해 제시하지 않는다. 사용자가 특정 ID를 원하면 자유 입력을 그대로
받는다. `economy`, `caveman`, `local_first`는 질문하지 않고 기본값을 쓴다.

`claude_model` / `claude_effort`는 **Claude worker**에만 적용된다. Coordinator
세션 자체의 모델과 effort는 Skill이 바꿀 수 없고 사용자가 `/model`, `/effort`로
정한다. 2차 질문에 이 사실을 한 줄로 표시한다.

## 3. Run 디렉터리

```text
<WIKI_ROOT>/LLM-Workspace/Runs/YYYY-MM-DD-HHmmss-<goal-slug>/
├─ 00-run.md
├─ 10-context-pack.md
├─ 20-plan.md
├─ 20-plan.brief.md
├─ 30-coder-handoff.md
├─ 40-coder-report.md
├─ 50-worker-handoff.md
├─ 60-worker-report.md
├─ 70-corrections.md
├─ 90-final-review.md
├─ 99-state.md
└─ artifacts/
   ├─ context-manifest.json
   ├─ repo-tree.txt
   ├─ symbols.txt
   ├─ full.diff
   ├─ build.log
   ├─ test.log
   └─ lint.log
```

`goal-slug`: 영문 소문자·숫자·하이픈, 6단어 이내. 사용하지 않는 단계 파일은
만들지 않는다. `pipeline-defaults.json`은 Run 바깥, `Runs/`와 같은 수준.

## 4. 문서 크기 상한

```text
00-run.md            80줄
10-context-pack.md   200줄 또는 12KB
20-plan.md           150줄 또는 12KB
20-plan.brief.md     80줄 또는 6KB
30-coder-handoff.md  100줄 또는 8KB
40-coder-report.md   100줄 또는 8KB
50-worker-handoff.md 80줄 또는 6KB
60-worker-report.md  100줄 또는 8KB
90-final-review.md   120줄 또는 10KB
99-state.md          40줄
```

먼저 도달하는 제한을 적용한다. 초과하면 잘라내는 대신 raw를 `artifacts/`로 옮기고
문서에는 경로만 남긴다.

## 5. artifacts 규칙

raw 로그, 전체 diff, 대량 파일 목록, 심볼 인덱스는 Markdown에 넣지 않는다.
`artifacts/`에 저장하고 요약 문서에서 **절대경로만** 참조한다.
로그는 `scripts/run-captured.sh`로 캡처한다.

## 6. 문서 frontmatter

실제로 아는 값만 기록한다. ID는 추측하지 않는다. 가능한 필드:
`run_id`, `orca_run_id`, `orca_task_id`, `orca_dispatch_id`, `role`, `agent`,
`status`, `goal`, `repository`, `worktree`, `branch`, `created_at`,
`updated_at`, `input_files`, `output_files`, `artifacts`, `previous_handoff`,
`next_handoff`.

문서 간 이동은 Obsidian 링크로 한다: `[[00-run]]` `[[10-context-pack]]`
`[[20-plan]]` `[[20-plan.brief]]` `[[30-coder-handoff]]` `[[40-coder-report]]`
`[[50-worker-handoff]]` `[[60-worker-report]]` `[[70-corrections]]`
`[[90-final-review]]` `[[99-state]]`.

## 7. 문서별 필수 내용

**00-run.md** — 사용자 원문 목표, planner/coder/worker와 각 출처
(`explicit`/`remembered`/`asked`), economy·caveman·codex_effort·local_first,
Wiki 절대경로와 경로 출처, 저장소 절대경로, branch, worktree, Orca Run ID,
시작 시각, 단계별 진행표, §9 token 표.

```markdown
| Stage | Agent | Status | Task | Dispatch | Record |
|---|---|---|---|---|---|
| Scout | opencode | pending | - | - | [[10-context-pack]] |
| Plan | claude | blocked | - | - | [[20-plan]] |
| Implement | codex | blocked | - | - | [[40-coder-report]] |
| Verify | opencode | blocked | - | - | [[60-worker-report]] |
| Review | claude | blocked | - | - | [[90-final-review]] |
```

**10-context-pack.md** — 목표 관련 파일, 정확한 line range, 관련 symbol, 호출
관계, 빌드·테스트 명령, 기존 사용자 변경, 위험, 미해결 질문, raw artifact 경로.
이것 외에는 넣지 않는다.

**20-plan.md** — Objective, Problem definition, Required changes, Files and
symbols(line range 포함), Out of scope, Interface and data flow, Error handling,
Implementation order, Build procedure, Test procedure, Acceptance criteria,
Failure and recovery criteria, Risks and assumptions.

**20-plan.brief.md** — 프론티어 모델 전달용 축약본. Objective, Required changes,
Files/symbols + line range, Out of scope, Acceptance criteria, Build/test 명령,
변경 금지 범위. 계획 원문을 덮어쓰지 않고 별도 파일로 만든다.

**30-coder-handoff.md** — Goal, Assigned agent, `[[20-plan.brief]]` 링크, 대상
파일과 line range, 변경 금지 범위, Acceptance criteria, Build/test 명령,
Known risks, 보존할 기존 사용자 변경, 금지 행위, 보고서 경로와 형식.

**40-coder-report.md** / **60-worker-report.md** — `agent-contracts.md`의 출력
형식을 따른다. 로그 본문 대신 artifact 경로.

**50-worker-handoff.md** — Goal, Assigned agent, `[[40-coder-report]]` 링크,
build/test/lint 명령, 남은 기계적 작업, 문서·정리 작업, 변경 금지 핵심 로직,
escalation 조건, 완료 기준.

**70-corrections.md** — correction 누적 기록. 항목마다: 번호, 역할, agent,
Task ID, Dispatch ID, 문제 파일, 문제 symbol, 관측 동작, 요구 동작, 실패 명령,
exit code, 결정적 로그 (artifact 경로), 요구 검증, 결과.

**90-final-review.md** — `review-policy.md` §4 형식.

**99-state.md** — `current_stage`, `overall_status`, `planner`, `coder`,
`worker`, `economy`, `active_task_id`, `active_dispatch_id`,
`last_completed_stage`, `next_stage`, `blocking_issue`, `correction_count`,
`last_updated`. 단계 변경 시 Coordinator가 갱신한다. 모든 agent는 작업 시작 시
이 파일을 가장 먼저 읽는다.

## 8. Wiki와 Orca 분리

Wiki 문서만 쓰고 Orca Task/Dispatch를 생략하면 안 된다. 반대로 Orca 메시지만
쓰고 Wiki handoff 문서를 생략해도 안 된다.

## 9. Token 기록

별도 `token-metrics.md`를 만들지 않는다. `00-run.md` 또는 `90-final-review.md`에
짧은 표로 남긴다. 기록 가능한 값만:

```markdown
| metric | value |
|---|---|
| claude usage start/end | |
| codex usage receipt | |
| opencode local | yes/no |
| claude 호출 단계 수 | |
| codex 호출 단계 수 | |
| codex 생략 여부 | |
| raw log 크기 | |
| frontier 전달 brief 크기 | |
| correction 횟수 | |
```

측정할 수 없는 값은 `n/a`로 둔다. 추정치를 실측처럼 적지 않는다.
