# Review Policy

## 1. Final review 입력

Claude는 전체 저장소나 raw artifacts를 자동으로 읽지 않는다. 기본 입력:

- `20-plan.brief.md`
- `40-coder-report.md`
- `60-worker-report.md`
- acceptance matrix
- `git diff --stat` (`artifacts/diff-stat.txt`)
- 고위험 변경의 **정확한 diff 범위만**

## 2. 상세 diff를 먼저 볼 대상 (고위험)

- public API
- 파일 형식과 persistence
- security
- concurrency
- lifetime 및 memory ownership
- 수치 알고리즘
- 물리 모델
- 경계조건
- 성능 핵심 경로
- 테스트가 실패한 부분

저위험 기계적 변경은 local verifier 결과 + targeted spot check로 검토한다.
전체 diff를 통째로 읽지 않는다.

검토 항목: 계획과 구현 일치, 범위 밖 변경 유무, API·ABI 호환성, ownership과
lifetime, 오류 처리, 경계조건, 수치적 의미 보존, 빌드·테스트·lint 결과, 새 경고,
acceptance criteria 충족.

Coordinator는 구현 파일을 직접 수정하지 않는다. 수정이 필요하면 correction Task.

## 3. Correction budget

```text
Planner correction            : 최대 1회
Codex correction              : 최대 1회
OpenCode mechanical correction: 최대 1회
```

라우팅: 핵심 구현 결함 → Codex. 포맷·문서·반복 수정·단순 빌드 문제 → OpenCode.
설계·요구사항 오해 → Planner.

같은 실패가 반복되면 추가 호출하지 않는다. 한도 초과나 반복 실패 시 성공으로
처리하지 않고, `70-corrections.md`와 `90-final-review.md`에 다음을 기록하고
종료한다.

- 실패 명령
- exit code
- 결정적 로그 (artifact 경로)
- 변경 파일
- 예상 원인
- 미충족 acceptance criteria
- 다음에 필요한 역할

## 4. 90-final-review.md 내용

Goal / planner / coder / worker / economy, Orca Run ID, Tasks와 Dispatches,
단계 요약, 변경 파일, 주요 구현 결정, 빌드·테스트 명령과 결과 (artifact 경로),
correction 이력, acceptance criteria 검토, 남은 위험, token 표
(`wiki-contract.md` §9), 그리고 결론부는 `agent-contracts.md` §5 형식.

## 5. Scope closure gate

최종 검토 시작 시 `90-final-review.md`에 현재 사용자 목표의 항목을 세 줄로 분류한다:
`required`, `optional/deferred`, `out-of-scope historical follow-up`. required만 완료를
막는다. `99-state.md`의 active/next, 오래된 roadmap, 이전 Run의 bisect가 있다는 이유만으로
optional·historical 항목을 새 Task로 시작하지 않는다. required acceptance가 충족되면 먼저
S7 sweep과 최종 응답을 끝내고, 후속은 명시적으로 별도 요청될 때만 새 Run으로 연다.

## 6. 완료 조건

모두 만족해야 완료다.

- 요청된 기능 또는 수정이 구현됐다
- 구현이 승인된 계획과 일치한다
- 관련 없는 변경이 없다
- 빌드가 성공했다
- 관련 테스트가 성공했다
- 실패와 경고가 숨겨지지 않았다
- acceptance criteria가 충족됐다
- unresolved escalation이 없다
- 필요한 Wiki 보고서가 모두 작성됐다
- worker terminal이 모두 release됐다 (`worker-list --terminal-state reclaimable`이
  비어 있음). `retained`가 있으면 이유가 `90-final-review.md`에 적혀 있다
- `99-state.md`가 completed로 갱신됐다

실행하지 않은 테스트를 성공했다고 보고하지 않는다. 빌드·테스트 결과는
`artifacts/`의 실제 로그와 exit code에 근거해야 한다.
