# Token Policy

목표는 유료 모델 호출 회피와 입력 컨텍스트 축소다. 출력 문체 압축은 그다음이다.
correctness와 작업 성공률이 토큰 절감보다 우선한다.

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
