# Orca Runtime

Orca는 **실행 권위자**다: Run, Task, Dispatch, worker lifecycle, terminal,
`worker_done`, `question`, `escalation`, completion status.

## 1. CLI

이 환경의 Orca CLI는 항상 `orca-ide`다. 다른 실행 파일 이름, `ORCA_CLI_COMMAND`,
`/usr/bin/` 경로를 쓰지 않는다. live guide가 접미사 없는 짧은 CLI 이름으로 예시를
출력해도 실행은 `orca-ide`로 치환한다. guide가 구조화된 next-step 인수를 반환하면
그 인수를 그대로 `orca-ide`에 붙여 실행한다. 인수를 기억으로 번역하지 않는다.

## 2. 부트스트랩

```bash
orca-ide status --json
orca-ide skills get orchestration
```

- `status --json` 실패 시 정확한 오류 문자열을 보고하고 중단한다. runtime이 ready가
  아니면 진행하지 않는다.
- `skills get orchestration`이 반환한 **현재 설치 버전 guide**를 읽고, 하위 명령과
  옵션은 그 guide를 따른다. 오래된 기억으로 명령을 추정하지 않는다.
- guide와 이 Skill이 충돌하면: 명령 문법은 guide 우선, 역할·금지 규칙·Wiki 기록
  의무는 Skill 우선.

Run 생성:

```bash
orca-ide orchestration run-create --objective "<goal>" --json
```

반환된 ID를 기록한다. ID는 추측하거나 임의 생성하지 않는다.

## 3. Supervised worker loop

모든 역할은 같은 현재 worktree에서 순차 실행한다. 동시에 두 편집 agent를 돌리지
않는다. 개념적 형태 (정확한 문법은 live guide):

```bash
orca-ide orchestration task-create --spec "<stage task spec>" --json
orca-ide orchestration worker-start --task <task_id> --worktree current --agent <agent> --json
orca-ide orchestration check --wait --types worker_done,escalation,question --timeout-ms 900000 --json
orca-ide orchestration worker-release --dispatch <dispatch_id> --json
```

- 이전 단계가 완료·승인되기 전에 다음 단계 worker를 시작하지 않는다.
- 대기 중 timeout이나 `{count:0}`은 실패가 아니다. 코딩 작업 15–60분은 정상.
  `worker_done` / `escalation`을 받거나 terminal이 사라질 때까지 rolling wait.
- heartbeat나 terminal 활동만 보고 worker를 중단하지 않는다.
- Delivery의 모든 메시지를 처리한 뒤에만 ack 한다.
- `question`은 `orca-ide orchestration reply --id <msg_id> --body <answer> --json`.
- 수락된 `worker_done` 처리 후 즉시 다음 소유자를 정한다. 같은 agent의 즉시 후속
  Task가 있으면 terminal 재사용, 없으면 `worker-release`. **Codex는 Task 완료 후
  항상 release**해 후속 무관 작업이 같은 context에 누적되지 않게 한다.

### 모델과 생각 깊이 적용

`worker-start --agent <agent>`는 agent CLI를 기본 설정으로 띄운다. 모델이나
reasoning effort를 지정하려면 custom argv가 필요하므로 두 단계로 나눈다.

```bash
orca-ide terminal create --worktree active --title <stage> --command '<agent argv>' --json
orca-ide terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca-ide orchestration dispatch --task <task_id> --to <handle> --inject --json
```

argv 조립 규칙 — 이 Skill이 검증한 플래그만 쓴다.

| 대상 | 값 | argv |
|---|---|---|
| Claude | `claude_model=inherit`, `claude_effort=inherit` | `claude` |
| Claude | 모델 지정 | `claude --model <value>` |
| Claude | effort 지정 | `claude --effort <low\|medium\|high\|xhigh\|max>` |
| Codex | 모델·effort 모두 미지정 | `codex` |
| Codex | 모델 지정 | `codex --model <value>` |
| Codex | effort 지정 | `codex -c model_reasoning_effort="<value>"` |
| OpenCode | 기본 | `opencode` |
| OpenCode | 모델 지정 | `opencode --model <provider>/<model>` |
| OpenCode | variant 지정 | `opencode --model <p>/<m> --variant <effort>` |

OpenCode는 `opencode.json`의 `model` 기본값을 이미 떠 있는 세션에 적용하지 않는다.
모델을 바꾸려면 위 `--model` argv로 새 terminal을 띄운다.

- 둘 다 `inherit`/`default`이면 custom argv가 필요 없다. 그때는 `worker-start`를
  그대로 쓴다. 불필요한 두 단계 경로를 만들지 않는다.
- 실행 전에 해당 CLI가 그 플래그를 받는지 `--help`로 확인한다. 지원되지 않으면
  지정 없이 실행하고 그 사실을 `00-run.md`에 기록한다. 플래그를 추측하지 않는다.
- 두 단계 경로는 repo의 `wait-for-setup` 정책을 강제하지 못한다. 현재 worktree에서
  실행하는 이 파이프라인에는 해당하지 않지만, 새 worktree가 필요해지면 live guide의
  경고를 따른다.
- `dispatch --inject` 대상은 agent handle 하나뿐이다. 여러 handle에 중복 전달하지
  않는다.

## 4. 메시지 내용 제한

Orca 메시지에는 Task ID, Dispatch ID, status, Wiki report 절대경로, blocking
question만 넣는다. 상세 보고서·계획·로그를 본문에 중복하지 않는다.

Orca messaging 대상: question, answer, escalation, `worker_done`, status,
lifecycle control. 그 외 상세 내용은 전부 Wiki (`wiki-contract.md`).

## 5. Terminal 재사용

연속 역할에 같은 agent가 지정된 경우 (`coder=opencode worker=opencode` 등),
이전 Dispatch가 정상 종료된 뒤에만 재사용을 고려한다. 재사용 문법과 조건은 live
guide를 따른다. 활성 Dispatch가 종료되기 전에는 재사용하지 않는다. 상태가
불명확하면 새 terminal을 만든다.

## 6. 실패 처리

- `worker_done --outcome failed`: 보고서와 artifact를 읽고 correction budget
  (`review-policy.md` §3) 안에서 재배정한다.
- `escalation`: Coordinator가 판정한다. 고위험이면 Claude가 직접 판단하고, 그렇지
  않으면 해당 역할에 지시를 보강해 재배정한다.
- worker가 사라졌거나 상태 불명이면 live guide의 recovery 절차를 따른다.
  고정된 파괴적 시퀀스를 쓰지 않는다.
- `worker-stop` 후 그 Task는 `blocked`가 된다. 같은 Task를 다시 배정하려면 먼저
  `orca-ide orchestration task-update --id <task_id> --status ready --json`을
  실행한다. 그러지 않으면 dispatch가
  `Task ... is blocked; only ready tasks can be dispatched`로 거부된다.
- 이 호스트(WSL)에서 `terminal wait --for tui-idle`이 bridge 인자 오류로 실패할 수
  있다. 그때는 `terminal read`로 TUI 준비 상태를 확인하고 진행한다. 실패를 무시하고
  바로 dispatch하지 않는다.
- **custom argv 경로에서는 `worker_done`이 거부될 수 있다.** 실측: `terminal
  create` + `dispatch --inject`로 띄운 OpenCode worker가 보낸 `worker_done`이
  `The Dispatch capability is missing for the given dispatch ID`로 거부됐다.
  `worker-start`로 띄운 Codex worker는 정상 처리됐다. 그러므로 모델 override가
  필요 없으면 항상 `worker-start`를 쓴다. custom argv가 필요해서 거부가 발생하면,
  Coordinator가 산출물 파일을 직접 확인한 뒤
  `task-update --id <task_id> --status completed --result '<json>'`로 닫는다.
  worker의 보고 없이 성공으로 간주하지 않는다. 확인한 산출물 경로를 result에 남긴다.
