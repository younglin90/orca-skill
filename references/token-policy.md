# Token Policy

목표는 유료 모델 호출 회피와 입력 컨텍스트 축소다. 출력 문체 압축은 그다음이다.
correctness와 작업 성공률이 토큰 절감보다 우선한다.

## 0. 지배적 비용은 Coordinator의 왕복 횟수다

Coordinator 대화의 비용은 대략 Σ(각 API 호출 시점의 컨텍스트 크기)다. 컨텍스트는
매 호출마다 통째로 다시 읽히므로, 호출이 늘면 비용은 대화 길이에 대해 **제곱으로**
증가한다. 한 세션 실측 (444 API 호출):

```text
분위   호출수   평균 컨텍스트   그 구간 cache read
  1      44        56,838          2,500,915
  5      45       164,245          7,391,041
 10      45       305,407         13,743,334
```

같은 호출 수인데 마지막 구간이 첫 구간의 5.5배다. 같은 세션의 도구 결과 전부를
합쳐도 약 5만 토큰인데 cache read는 7,679만이었다. **개별 출력 크기가 아니라 왕복
횟수가 비용을 지배한다.**

따라서 규칙은 하나다. **오케스트레이션을 Coordinator 컨텍스트에 남기지 않는다.**

- worker 단계 하나는 `scripts/run-stage.sh`로 **호출 1회**에 끝낸다. task 생성,
  worker 시작, sentinel 폴링, 진단, nudge, `worker_done` 유예, task 닫기,
  teardown이 전부 그 안에서 일어나고 약 10줄짜리 영수증만 돌아온다.
  create → start → poll → read → nudge → poll → stop → update를 각각 따로 부르면
  같은 일에 8~15 왕복이 들고, 그 결과는 전부 영구히 컨텍스트에 남는다.
- worker 화면을 볼 때는 `scripts/worker-tail.sh`를 쓴다. `worker-read --json`
  원본은 TUI 박스 문자와 스피너 프레임으로 가득하다. 실측: 원본 4,611 bytes,
  필터 결과 594 bytes.
- 같은 reference 문서를 한 세션에서 두 번 읽지 않는다. §1의 manifest가 이것을 위한
  것이다.
- 폴링 간격을 좁혀도 정보는 늘지 않는다. `--interval-sec`은 15 이상으로 둔다.

### 0.1 Model-turn circuit breaker

2026-08-08 실측 Run은 5 worker에서 총 9,598,648 tokens를 기록했고 그중 94.6%가
cached input이었다. Verifier 119 token events/80 tool calls, Scout 28 events가 전체의
80.4%를 차지했다. 이를 기본 실패 모드로 취급한다.

| role | model tool-call 상한 | 초과 전 조치 |
|---|---:|---|
| Scout | 10 | targeted `rg` 결과를 context pack으로 즉시 고정 |
| Planner | 6 | 추가 탐색 중단, blocking assumption 기록 |
| Coder | 14 | 검증 명령을 인자 없는 batch runner로 통합 |
| Verifier | 12 | 완료된 receipt만 판정하거나 bounded blocker 기록 |

- 장기 명령 실행을 LLM 감독 loop에 넣지 않는다. 반복 `ps`, `tail`, 로그 크기 확인,
  같은 프로세스 상태 조회는 금지한다. deterministic runner가 종료 조건·timeout·로그
  요약을 책임지고 model에는 최종 receipt 한 번만 돌려준다.
- `repo-tree.txt`와 `symbols.txt`는 탐색 힌트다. 전문 읽기·prompt 첨부를 금지하고
  goal 기반 targeted `rg`를 쓴다. 기본 수집기는 각각 line/byte cap을 적용한다.
- Coder terminal은 즉시 S4 acceptance review가 끝날 때까지 유지한다. correction이
  필요하면 같은 terminal에 한 번만 후속 Task를 보내고, 승인 즉시 release한다.
- tool-call 상한 때문에 acceptance를 생략하지 않는다. 증명할 수 없으면 성공 대신
  bounded blocker로 닫는다.

세션을 새로 시작하는 것도 효과가 있지만 유일한 수단이 아니고, 진행 중인 작업에는
쓸 수 없다. 위 규칙은 같은 세션 안에서 적용된다.

## 1. Context admission gate

Claude 또는 Codex가 새 파일을 읽기 전에 다음을 확보한다.

```yaml
path:
reason:
required_lines:
source_stage:
content_hash:
```

가능하면 `artifacts/context-manifest.json`을 사용한다
(`scripts/build-context-manifest.py`).

- 파일 전체 읽기보다 정확한 line range를 우선한다.
- `build-context-manifest.py <run_dir> check --path P`가 exit 0이면 같은 단계에서
  다시 읽지 않는다.
- 선행 agent가 이미 제공한 내용을 긴 프롬프트로 재설명하지 않는다. Wiki 절대경로를
  전달한다.
- 프론티어 모델에는 전체 저장소, 전체 Wiki, raw 로그를 넘기지 않는다.

## 2. Brief 생성

프론티어 모델 입력은 원문이 아니라 `.brief.md`를 쓴다. brief는 OpenCode가 만든다.
계획 원문을 덮어쓰지 않고 별도 파일로 둔다 (`wiki-contract.md` §7).

## 3. 로그 처리 경로

```text
명령 → scripts/run-captured.sh → artifacts/*.log
     → scripts/summarize-log.sh (deterministic pattern)
     → 부족할 때만 OpenCode가 raw log 요약
     → Claude/Codex에는 요약 + artifact 경로만
```

Claude나 Codex에 raw 로그 전체를 직접 전달하지 않는다.

## 4. Caveman 압축 정책

외부 Skill 설치 여부에 의존하지 않는다. 이 문서의 규칙만 따른다.
`ultra` 수준은 사용하지 않는다.

### Claude / Codex — 기본 `caveman=lite`

- 인사, filler, hedging 제거
- 질문 재진술 제거
- 중복 요약 제거
- 결론과 필요한 근거만
- 정상 문장과 기술적 정확성 유지

`caveman=off`면 압축 없이 평문. `caveman=full`이어도 Claude/Codex 출력은 `lite`
수준을 넘지 않는다 (기술 정확성 손실 위험).

### OpenCode

상태 및 agent-to-agent 보고는 `full` 허용. 형식:

```text
path:line — symbol — finding
command — exit code — result — artifact
risk — evidence — required owner
```

### 압축 금지 대상

다음은 어떤 수준에서도 압축·재작성·의역하지 않는다. 원문 그대로 옮긴다.

- code block, inline code
- 명령, 경로, symbol
- 오류 핵심 줄, diff anchor
- 부정어, 예외 조건
- 수치, 단위, 허용오차
- API contract, acceptance criteria
- 보안 경고, 비가역 작업 경고

## 5. Session discipline

- 무관한 작업을 같은 Run에 추가하지 않는다. 새 목표는 새 Run.
- 모든 worker는 stage settled 즉시 자동 release한다 (`orca-runtime.md` §3).
  Coordinator 세션은 종료하지 않는다.
- OpenCode terminal 재사용은 같은 역할의 즉시 후속 Task에만 허용한다. 그 후속
  Task가 끝나면 release한다.
- Run 종료 전 `worker-list --terminal-state reclaimable` sweep을 반드시 돈다.
- 동일 문서를 반복해서 prompt에 붙이지 않는다. Wiki path로 참조한다.
- 상태 보고만을 위한 agent 호출을 만들지 않는다. `99-state.md`로 대신한다.
- worker timeout을 실패로 간주하지 않는다.
- Claude agent team을 사용하지 않는다.
- 동일 작업을 Claude, Codex, OpenCode에 중복 조사시키지 않는다.

## 6. Token 측정

기록 위치와 항목은 `wiki-contract.md` §9. 측정할 수 없는 값을 추정해 실제 수치처럼
기록하지 않는다.
Codex task가 있으면 `scripts/report-token-usage.py`에 Task ID를 넘겨 worker session의
마지막 token receipt를 수집한다. total, cached input, uncached input, output, model
tool-call 수를 분리한다. cached token을 신규 token 또는 실제 비용으로 부르지 않는다.
