# Agent Contracts

각 역할의 입력, 금지 사항, 출력 형식. Task spec에는 이 형식을 그대로 요구한다.
상세 보고서를 Orca 메시지 본문에 중복하지 않는다 (`orca-runtime.md` §4).

## 공통

모든 worker Task spec에 다음을 넣는다.

1. 먼저 읽을 파일의 **절대경로** (아래 각 역할의 "입력"만)
2. 금지 사항
3. 산출물 파일의 절대경로
4. 출력 형식 (아래 블록)
5. 완료 시 `worker_done` 전송, 본문에 산출물 절대경로 포함

모든 worker 공통 금지:

- destructive Git 명령 금지
- commit / push / merge / rebase 임의 수행 금지
- 기존 사용자 변경 훼손 금지
- 실패 결과 은폐 금지
- 계획 문서(`20-plan.md`) 임의 변경 금지
- 자기 역할 밖 파일 수정 금지

### 로컬 모델(OpenCode) Task spec 강화

작은 로컬 모델은 존재하지 않는 툴을 호출하다 정지하는 경우가 있다 (실측: `explore`
툴 반복 호출 후 stall). OpenCode에 보내는 spec에는 반드시 다음을 넣는다.

1. 사용할 툴을 명시한다: `read`, `write`, `bash`, `grep`, `glob`만 쓴다.
   `explore`, `task`, subagent, 그 밖의 툴 이름을 만들어 부르지 않는다.
2. 첫 동작을 지시한다: 먼저 산출물 파일을 만들고, 채워 넣은 뒤 완료한다.
3. 자유 탐색 대신 **실행할 명령을 그대로 적어 준다**. 예:
   `grep -n "add_test" CMakeLists.txt`, `head -100 <artifact>`.
4. 완료 명령에 placeholder를 남기지 않는다. Dispatch ID는 Task 생성 시점에 아직
   없으므로, worker 시작 직후 실제 ID가 들어간 **완성된 한 줄**을 follow-up 메시지로
   보낸다 (`orca-ide orchestration send --to dispatch:<id> --subject "completion
   command" --body "<literal command>"`). 작은 모델이 preamble에서 ID를 찾아
   조립하도록 기대하지 않는다.
5. 단계 수를 제한한다: "탐색은 5개 명령 이내, 그 다음 바로 파일 작성."
6. 로컬 모델의 context window는 작을 수 있다. artifact 전체를 읽으라고 하지 말고
   `head`/`grep`로 필요한 부분만 보게 한다.
7. **한 메시지에 한 동작.** 실측에서 다단계 spec을 한 번에 준 로컬 worker는
   생각만 하고 툴을 호출하지 않았다. 같은 모델에 `"Use the write tool now to
   create <path> containing ..."`처럼 단일 명령형으로 주면 즉시 수행했다.
   따라서 로컬 단계는 Coordinator가 `terminal send`로 한 단계씩 밀어 준다:
   ① 파일 생성 → ② 조사 명령 1개 → ③ 결과 반영 → ④ 완료 보고.
   각 메시지는 `Run this exact command now:` / `Use the write tool now to ...`로
   시작하고 대안이나 배경 설명을 붙이지 않는다.
8. **spec 자체를 짧게 유지한다: 25줄 이내.** 실측에서 ollama `gemma4:26b`의
   `num_ctx`가 4096이었고, 40줄짜리 spec을 준 worker는 툴 호출 없이 생성만 하다
   멈췄다. 단계 배정 전에 로컬 모델의 실제 context 크기를 확인한다:

   ```bash
   curl -s http://localhost:11434/api/ps | python3 -m json.tool | grep context_length
   ```

   `context_length`가 8192 미만이면 그 단계를 로컬에 배정하지 않거나, spec을
   10줄 이하 + 명령 2개로 더 줄인다. 사용자에게 `num_ctx` 상향을 제안할 수는
   있으나 Skill이 Ollama 설정을 임의로 바꾸지 않는다. 실측 기준: 4096은 실패,
   16384는 정상 동작.
9. **Wiki는 반드시 worktree 안에 둔다.** OpenCode는 worktree 밖 경로에 쓰려 할 때
   `Permission required — Access external directory` 프롬프트에서 멈추고, 그
   상태로 무한 대기한다. 기본값 `$REPO_ROOT/LLM-Wiki`가 이 문제를 피한다.
   사용자가 worktree 밖 vault를 지정하면, 로컬 worker 배정 전에 그 경로에 대한
   OpenCode 권한이 필요하다고 사용자에게 알린다.

로컬 worker가 3회 이상 무효 툴 호출을 하거나 진전 없이 멈추면 `worker-stop` 후
같은 spec을 더 좁혀 1회 재시도한다. 재시도도 실패하면 그 단계는 Coordinator가
deterministic 도구로 수행하고 그 사실을 `00-run.md`에 기록한다. 실패를 숨기고
성공으로 넘어가지 않는다.

## 1. Local scout (opencode)

입력: `99-state.md`, `artifacts/repo-tree.txt`, `artifacts/symbols.txt`,
`artifacts/git-status.txt`, `artifacts/diff-stat.txt`, 사용자 goal.

작업: goal과 관련된 파일·line range·symbol·호출 관계를 좁힌다. 빌드·테스트 명령을
찾는다. 운영 코드를 수정하지 않는다.

산출물: `10-context-pack.md` (200줄/12KB 상한), 그리고 선별한 각 파일을
`scripts/build-context-manifest.py <run_dir> add ...`로 manifest에 등록.

출력 형식:

```text
path:line-range — symbol — relevance
build: <command>
test: <command>
risk: <short evidence>
question: <only if blocking>
```

## 2. Planner (claude 기본)

입력: `10-context-pack.md`, `99-state.md`. **이 둘만 읽는다.**

context pack이 불충분하거나 신뢰할 수 없을 때만 정확한 추가 line range를 읽고,
그 사실과 이유를 `20-plan.md`의 Risks에 기록한다. 저장소 전체 재탐색 금지.

산출물: `20-plan.md`. 이어서 `20-plan.brief.md`는 OpenCode가 생성한다.

`planner=claude`면 Coordinator가 직접 수행하고 별도 Claude worker를 만들지 않는다.
`planner=codex|opencode`면 supervised worker를 만든다.

## 3. Coder (codex 기본)

입력 — 이것만 전달한다:

- `20-plan.brief.md` 절대경로
- `30-coder-handoff.md` 절대경로
- 대상 파일과 line range
- acceptance criteria
- 변경 금지 범위
- 실행할 테스트 명령
- 보고서 작성 경로 (`40-coder-report.md`)

Coder에게 **요청하지 않는다**:

- 저장소 전체 재조사
- 전체 Wiki 읽기
- 전체 로그 읽기
- 전체 history 재구성
- Planner 조사 반복
- 일반 문서·포맷·로그 작업

계획과 실제 코드가 충돌하면 구현을 강행하지 말고 Orca `ask` 또는 `escalation`.

출력 형식 (`40-coder-report.md`):

```text
changed:
- path:line-range — change
verified:
- command — exit code
deviation:
- none | concise reason
risk:
- none | concise evidence
report: <wiki-path>
```

명령은 `scripts/run-captured.sh`로 실행해 로그를 `artifacts/`에 남기고 보고서에는
exit code와 artifact 경로만 적는다.

## 4. Local verifier / worker (opencode)

입력: `99-state.md`, `50-worker-handoff.md`, `artifacts/full.diff`.

작업: 전체 diff 검토, 빌드·테스트·lint 실행, 로그 분류, 포맷·import·주석·문서
정리, 임시 파일 정리, 기계적 반복 수정.

금지:

- 새 아키텍처 도입
- 핵심 알고리즘 임의 변경
- public API 임의 변경
- 수치적 의미·물리 모델 임의 변경
- 핵심 구현 결함 우회 (직접 고치지 말고 escalate)

출력 형식 (`60-worker-report.md`):

```text
build: pass|fail — artifact
test: pass|fail — artifact
lint: pass|fail|not-run — artifact
findings:
- path:line — severity — problem
core_issue: none|escalate-to-coder
```

## 5. Reviewer (claude, Coordinator 본인)

입력과 범위는 `review-policy.md`.

출력 형식 (`90-final-review.md` 결론부):

```text
acceptance: pass|fail
high-risk findings:
- path:line — issue — required action
unverified:
- check
final: accepted|correction-required|failed
```

## 6. Coordinator

Coordinator는 현재 Claude 세션이며 역할 인수로 바꿀 수 없다.

책임: 인수 파싱·검증, Wiki 경로·역할 결정과 기억 갱신, Orca 부트스트랩, Run 생성,
Run 디렉터리 생성, deterministic context 수집 실행, 단계별 Task 생성과 Dispatch,
question/escalation 처리, 단계 결과 승인, local implementation gate 판정,
correction 배정, 최종 검토, 최종 보고.

Coordinator가 직접 쓰는 파일은 Wiki Run 디렉터리 안의 Markdown뿐이다. 운영 소스,
테스트, 빌드 파일, 프로젝트 설정을 직접 수정하지 않는다. 구현 결함은 correction
Task로 넘긴다.
