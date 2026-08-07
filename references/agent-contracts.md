# Agent Contracts

각 역할의 입력, 금지 사항, 출력 형식. Task spec에는 이 형식을 그대로 요구한다.
상세 보고서를 Orca 메시지 본문에 중복하지 않는다 (`orca-runtime.md` §4).

## 공통

모든 worker Task spec에 다음을 넣는다.

1. 먼저 읽을 파일의 **절대경로** (아래 각 역할의 "입력"만)
2. 금지 사항
3. 산출물 파일의 절대경로
4. 출력 형식 (아래 블록)
5. 완료 방식. agent에 따라 갈린다.
   - Codex·Claude worker: 완료 시 `worker_done` 전송, 본문에 산출물 절대경로 포함.
   - 로컬 모델 OpenCode worker: lifecycle 메시지를 요구하지 않는다. 보고서 파일과
     sentinel 파일을 쓰게 하고 Coordinator가 Task를 닫는다
     (`orca-runtime.md` §7).

모든 worker 공통 금지:

- destructive Git 명령 금지
- commit / push / merge / rebase 임의 수행 금지
- 기존 사용자 변경 훼손 금지
- 실패 결과 은폐 금지
- 계획 문서(`20-plan.md`) 임의 변경 금지
- 자기 역할 밖 파일 수정 금지

### 로컬 모델(OpenCode) Task spec 강화

배정 전에 `orca-runtime.md` §7 "환경 전제"를 먼저 확인한다. 전제가 깨져 있으면
spec을 아무리 다듬어도 실패한다.

작은 로컬 모델은 존재하지 않는 툴을 호출하다 정지하는 경우가 있다 (실측: `explore`
툴 반복 호출 후 stall). OpenCode에 보내는 spec에는 반드시 다음을 넣는다.

1. 사용할 툴을 명시한다: `read`, `write`, `bash`, `grep`, `glob`만 쓴다.
   `explore`, `task`, subagent, 그 밖의 툴 이름을 만들어 부르지 않는다.
2. 첫 동작을 지시한다: 먼저 산출물 파일을 만들고, 채워 넣은 뒤 완료한다.
3. 자유 탐색 대신 **실행할 명령을 그대로 적어 준다**. 예:
   `grep -n "add_test" CMakeLists.txt`, `head -100 <artifact>`.
   같은 이유로 **선택 추출을 시키지 않는다.** 실측: 120줄 문서를 보여 주고
   "이 7개 섹션만 골라 그대로 옮겨라"라고 한 로컬 worker는 파일을 읽은 뒤 정지했다.
   어느 줄이 어느 섹션인지 판단하는 것 자체가 부담이다. Coordinator가 먼저
   `grep -n '^## '`로 섹션 line number를 확인하고, spec에는 **정확한 range 한 줄**을
   준다.

   ```bash
   # 나쁨: Copy the Objective, Files and symbols, Acceptance criteria sections
   # 좋음:
   sed -n '17,21p;38,77p;96,119p' <plan> > <brief>
   ```

   같은 worker가 선택 추출에서 멈춘 직후 이 range 명령을 받고는 즉시 성공했다.
   요약·재작성이 정말 필요하면 그 단계는 로컬에 배정하지 않는다.
4. **완료를 명령 전송으로 요구하지 않는다.** 실측에서 완성된 리터럴 한 줄을
   주입해도 로컬 모델이 실행하지 못했다. 대신 spec의 마지막 단계를 파일 작성으로
   고정한다: 보고서 파일을 쓴 뒤 sentinel 파일에 `ok` 한 줄을 쓴다. 경로와 판정
   절차는 `orca-runtime.md` §7. spec 문구 예:

   ```text
   LAST STEP: use the write tool to create
   /abs/run_dir/artifacts/done/scout.done containing exactly one line: ok
   ```
5. 단계 수를 제한한다: "탐색은 5개 명령 이내, 그 다음 바로 파일 작성."
6. 로컬 모델의 context window는 작을 수 있다. artifact 전체를 읽으라고 하지 말고
   `head`/`grep`로 필요한 부분만 보게 한다.
7. **spec은 실패할 수 없어야 한다. 단계 수는 상관없다.**

   초기 관찰은 "3단계 뒤에 멈춘다"였고 한때 이 문서도 그렇게 적었다. 통제 실험이
   그것을 반증했다. Ollama OpenAI-호환 엔드포인트에 툴 정의를 주고 에이전트 루프를
   그대로 재현했을 때, `gemma4-32k:12b`와 `qwen3-32k:8b`는 **5단계 계획을 5/5로
   완주**했다. 툴 12개를 줘도, 400줄짜리 로그를 툴 결과로 넣어도, 64자짜리 긴 인자를
   시켜도, 시스템 프롬프트를 크게 해도 완주했다.

   실제로 죽는 조건은 하나다. **툴이 에러를 한 번 반환하면 회복하지 못한다.**
   `edit`이 `oldString not found`를 반환하게 하고 10턴을 관찰한 결과:

   ```text
   gemma4  T1:read T2:edit T3:read T4:list T5:read T6:bash T7:bash T8:bash T9:grep T10:list
           → 10턴 배회, 완료 파일 끝내 못 만듦
   qwen3   T1:STOP-EMPTY  → 아무 툴도 호출하지 않음
   ```

   무한 재시도가 아니라 전략 전환 실패다. 계획으로 돌아오지 못한다. 실제 Run에서
   3번째 호출 뒤 멈춘 것처럼 보인 이유는 그 시점에 늘 무언가 실패했기 때문이다
   (S4는 `edit` 실패, S5는 cwd 누락으로 인한 `ENOENT`). 단계 수는 상관관계였다.

   따라서 spec을 짧게 만드는 대신 **실패 지점을 없앤다.**

   - 모든 경로를 Coordinator가 먼저 존재 확인한 절대경로로 준다.
   - 모든 명령에 cwd를 고정한다 (아래 9번).
   - `edit` 툴 사용을 지시하지 않는다. 기존 파일 수정은 `write`로 전체를 다시 쓰게
     하거나 `artifacts/`의 패치 스크립트를 실행시킨다
     (`orca-runtime.md` §3 spec 인용 규칙).
   - 존재 여부가 불확실한 대상은 로컬에 배정하지 않는다.

   그럼에도 에러가 한 번 나면 **재시도시키지 않고 즉시 회수한다**. 배회하는 10턴은
   순수 낭비이고, 그 사이 worker가 잘못된 경로에 파일을 쓸 수 있다 (실측: `LLM-Wiki`
   대신 `LLM_Wiki`에 보고서와 sentinel을 작성했다). 회수 후 그 단계는 Coordinator가
   deterministic 도구로 처리하거나 Coder에게 넘긴다.
8. **spec 자체를 짧게 유지한다: 25줄 이내.** 실측에서 40줄짜리 spec을 준 로컬
   worker는 툴 호출 없이 생성만 하다 멈췄다. 실효 context 확인과 하한은
   `orca-runtime.md` §7 "환경 전제"에서 다룬다. 하한을 만족해도 spec 길이 규칙은
   유지한다. 짧은 spec은 compaction뿐 아니라 주의 분산도 줄인다.
9. **모든 명령에 작업 디렉터리를 명시한다.** worker의 cwd는 worktree 루트다.
   하위 패키지의 명령을 그냥 적으면 엉뚱한 곳에서 돌아 실패한다. 실측: `npm test`만
   적은 spec이 저장소 루트에서 실행돼
   `Could not read package.json: ENOENT ... /ProjectRoot/package.json`으로 죽었다.
   `cd <절대경로> && <명령>` 형태로 쓴다. 이건 모델의 실패가 아니라 spec의 결함이다.
10. **Wiki는 반드시 worktree 안에 둔다.** OpenCode는 worktree 밖 경로에 쓰려 할 때
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
로컬 모델이면 마지막에 `artifacts/done/scout.done`도 쓴다 (`orca-runtime.md` §7).

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

로컬 모델이면 보고서를 쓴 다음 `artifacts/done/verify.done`을 쓴다
(`orca-runtime.md` §7). Coordinator는 sentinel이 아니라 위 형식으로 성공을 판정한다.

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
