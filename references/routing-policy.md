# Routing Policy

작업을 가장 싼 실행자에게 배정하는 규칙. 우선순위:
deterministic tool > local OpenCode > Codex > Claude.

## 1. Deterministic tools first

LLM을 부르기 전에 셸·정적 도구로 처리한다. 이 목록의 작업에 어떤 LLM도
배정하지 않는다.

- `git status`, `git diff --stat`, `git diff` 저장
- 파일 목록, 디렉터리 트리
- `rg` 텍스트·심볼 검색, `ctags` 인덱스
- build target, test target 열거
- lint, formatter 실행
- line count, 파일 hash
- 로그에서 실패 패턴 추출 (`scripts/summarize-log.sh`)

`scripts/collect-context.sh`가 위 산출물을 `artifacts/`에 만든다.

## 2. Local OpenCode first (기본 실행자)

다음은 기본적으로 OpenCode/Ollama에 배정한다.

- 저장소 scout, 관련 파일·line range 선별
- symbol·호출 관계 요약, context pack 생성
- Wiki 문서 생성·갱신, `.brief.md` 생성
- raw 로그 분류, diff summary
- 빌드·테스트·lint 실행과 결과 정리
- 포맷팅, import 정리, rename, 단순 반복 수정
- 문서와 주석, 테스트 fixture, acceptance matrix 초안
- 저위험 단일 파일 수정, 기계적인 1~2개 파일 수정

## 3. Coordinator only (frontier 판단)

아래는 Coordinator가 직접 판단한다. 여기서 말하는 Coordinator는 이 Skill을 실행 중인
세션이며 Claude일 수도 Codex일 수도 있다. 판단의 근거는 모델 이름이 아니라 **이 항목들이
위임하면 안 되는 종류의 결정**이라는 점이다. 그 외 단계에는 Coordinator를 실행자로
배정하지 않는다 — 배정하면 위임의 의미가 사라진다.

- 목표와 요구사항 해석
- 아키텍처 결정, 불명확한 설계 판정
- public API 정책
- 보안·데이터 손실 위험 판정
- 수치 알고리즘과 물리적 의미
- acceptance criteria 승인
- 최종 고위험 검토 (`review-policy.md`)

## 4. Codex only when needed

- 핵심 구현
- 여러 파일 간 일관된 변경
- 복잡한 디버깅
- API·자료구조 변경
- concurrency
- lifetime 및 memory ownership
- 성능 핵심 경로
- 수치 알고리즘
- 로컬 모델이 실패한 구현
- Claude가 고위험으로 분류한 작업

## 5. economy 모드

| 모드 | 동작 |
|---|---|
| `max` (기본) | 저위험 작업은 OpenCode가 먼저 구현. Codex는 §6 gate를 통과하지 못할 때만 호출. Claude는 계획 승인 + 고위험 검토만. |
| `balanced` | Claude 계획, Codex 핵심 구현, OpenCode 조사·검증. 저위험 local 선구현 생략. |
| `off` | 인수로 지정된 역할 배정을 그대로 따름. local-first gate 비활성. |

`local_first=false`면 `economy` 값과 무관하게 §6 local implementation gate를
건너뛰고 Coder 역할 agent가 바로 구현한다.

## 6. Low-risk local implementation gate

`economy=max` 그리고 `local_first=true`일 때만 적용.

OpenCode가 먼저 구현할 수 있는 저위험 작업:

- 문서, 주석, formatting, lint, import, rename, boilerplate
- test fixture
- 명확한 단일 파일 수정, 기계적인 1~2개 파일 수정
- exact compile error 수정
- 계획에 완전히 명시된 반복 수정

OpenCode 구현 후 아래를 **모두** 만족하면 Codex를 호출하지 않는다.

1. 관련 빌드 성공
2. 관련 테스트 성공
3. 변경이 계획 범위 안에 있음
4. public API 변경 없음
5. architecture 변경 없음
6. 수치 의미 변경 없음
7. security-sensitive 변경 없음
8. Coordinator가 diff summary를 승인함

하나라도 실패하면 Codex correction Task 또는 Codex 핵심 구현 Task를 만든다.
판단 근거를 `40-coder-report.md`에 한 줄로 남긴다.

## 7. codex_effort

`codex_effort=auto`일 때 매핑:

```text
low    : 정확한 파일이 지정된 작은 변경 / 단순 테스트 추가 / 국소적 버그 수정
medium : 일반적인 여러 파일 기능 / 보통 수준의 디버깅
high   : 복잡한 상태 관리 / API·자료구조 변경 / 성능 핵심 코드
xhigh  : 수치 알고리즘 / concurrency / 메모리 안전성 / 매우 어려운 다중 모듈 문제
```

실행 시점에 설치된 Codex CLI가 reasoning effort를 어떻게 받는지 확인한다
(`codex --help`). 지원되지 않는 옵션을 추측하거나 강제로 전달하지 않는다.
확인할 수 없으면 effort 지정 없이 실행하고 그 사실을 `00-run.md`에 기록한다.

## 8. 중복 조사 금지

같은 질문을 Claude, Codex, OpenCode에 중복해서 조사시키지 않는다. 이미
`10-context-pack.md`에 있는 내용은 재조사 대상이 아니라 참조 대상이다.
