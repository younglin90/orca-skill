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
- **기본은 즉시 종료다.** 수락된 `worker_done` (또는 `--outcome failed` 확정)
  직후 그 dispatch를 `worker-release` 한다. 다음 단계 계획을 세우기 전에 release가
  먼저다. Coordinator terminal은 절대 release 대상이 아니다.
- 예외: Coder 구현 직후의 S4 acceptance review와 그 결과로 생기는 1회 correction은
  같은 agent/context의 확정된 연속 작업이다. review가 끝날 때까지만 terminal을
  유지하고, 승인 또는 correction 종료 즉시 release한다 (§5).
- release는 산출물을 지우지 않는다. terminal이 닫힌 뒤에도 `worker-read`는 보존된
  output archive를 반환한다. 로그를 보려고 terminal을 살려둘 이유는 없다.
- 디버깅을 위해 사용자가 명시적으로 살려두라고 한 worker만
  `worker-retain --dispatch <id>`로 예외 기록한다. 나중의 명시적 `worker-release`가
  이 예외를 해제하고 종료시킨다.

### spec 인용 규칙

`--spec` 값은 CLI 인수 파서를 통과한다. 실측에서 다음이 깨졌다.

- spec 안의 큰따옴표 `"`: 파서가 그 지점에서 인수를 다시 쪼개
  `Unknown command: orchestration task-create <spec 뒷부분>`으로 실패한다.
- spec 안의 heredoc(`<<EOF`)과 `$(...)`: 셸이 먼저 먹거나 파서가 깨진다.

따라서 spec 본문에는 큰따옴표를 쓰지 않는다. 문자열 리터럴이 필요하면 홑따옴표를
쓰고, 실행할 코드가 복잡하면 **Run 디렉터리 `artifacts/`에 스크립트 파일로 저장한
뒤 spec에는 그 절대경로 한 줄만** 넣는다. 스크립트는 실패 시 nonzero로 끝나게
작성해 no-op을 성공으로 보고할 수 없게 한다.

`task-create` 응답에 `result`가 없으면 파싱 실패다. Task ID를 만들어 내지 말고
spec을 고쳐 다시 만든다.

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

## 5. Terminal 재사용 (예외 경로)

재사용은 기본이 아니다. §3의 즉시 종료 규칙이 기본이고, 재사용은 두 조건이 **모두**
성립할 때만 쓴다.

1. 다음 Task가 이미 확정됐고 소유 agent가 직전 worker와 같다. 여기에는 S4 구현
   직후 acceptance review에서 확정된 correction Task가 포함된다.
2. 이전 Dispatch가 정상 종료됐다.

재사용 문법과 조건은 live guide를 따른다. 활성 Dispatch가 종료되기 전에는 재사용하지
않는다. 상태가 불명확하면 재사용하지 않고 release 후 새 terminal을 만든다.

## 5.1 Run 종료 sweep

Run을 `completed`/`failed`로 닫기 전에, 남은 worker terminal이 없는지 확인한다.
Task status와 terminal 회수 상태는 별개다 — 완료된 Task가 살아있는 terminal을
그대로 들고 있을 수 있다.

```bash
orca-ide orchestration worker-list --run <run_id> --terminal-state reclaimable --json
```

반환된 각 dispatch를 `worker-release --dispatch <dispatch_id> --json` 한다.
`retained`로 나온 것은 사용자가 명시적으로 살려둔 것이므로 건드리지 않고 그
사실만 `00-run.md`에 남긴다.

- `already_released`와 `release_pending`은 성공이다 (exit 0). 재호출해도 안전하다.
- `release_unknown`만 실패다 (exit 1). 이때는 `worker-show`로 상태를 확인하고,
  coordinator가 만든 terminal임이 확실하면 `terminal close --terminal <handle>`로
  닫는다. 확실하지 않으면 닫지 않고 사용자에게 보고한다.
- `terminal stop --worktree`는 쓰지 않는다. 해당 worktree의 terminal을 무차별
  종료하므로 Coordinator 자신이나 사용자 terminal까지 죽인다.

`99-state.md`의 `overall_status`를 terminal 종료보다 먼저 쓰지 않는다. sweep 결과를
확인한 뒤 최종 상태를 기록한다.

**`worker-stop`으로 끝낸 dispatch는 영구적으로 `retained`로 남는다.** 실측: stop된
dispatch에 `worker-release`를 걸면 `dispatch_inactive`로 거부되고 상태가 바뀌지
않는다. 이건 누수가 아니라 Orca의 기록 방식이다. sweep은 `reclaimable`이 비었는지만
확인하고, 남은 `retained` 개수와 그 원인(재시도·실패로 stop한 dispatch)을
`90-final-review.md`에 한 줄로 적는다. `retained`를 0으로 만들려고 파괴적 명령을
찾지 않는다.

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
- **`worker-start`가 `input_accepted`를 반환해도 preamble이 유실될 수 있다.** 실측:
  agent CLI가 아직 뜨는 중이면 주입 텍스트가 TUI 명령 팔레트로 흘러들어가고 worker는
  TASK를 받지 못한 채 idle로 남는다. 증상은 timeout인데 산출물 파일이 하나도 없고
  `worker-read`에 TASK 블록이 보이지 않는 것이다. 이때는 `worker-stop` →
  `task-update --status ready` → `worker-start`로 재시작한다. spec을 고치거나 모델을
  탓하기 전에 **TASK 블록이 실제로 주입됐는지부터 확인한다.**
- **agent가 TASK를 받고도 스킬 라우팅으로 새어 나갈 수 있다. 주입 실패와 증상이
  다르다.** 실측 2026-08-07: codex worker가 2400초 timeout, 산출물 0, 저장소 변경
  0바이트로 끝났다. `worker-tail` 판정은 `preamble-missing`이 아니라 **`task-visible`**
  이었고 TASK 블록이 화면에 그대로 있었다. 실제로 한 일은:

  ```text
  Ran sed -n '1,260p' /home/younglin90/.agents/skills/orca-cli/SKILL.md
  Ran orca-ide skills get orca-cli && orca-ide status --json     (+389 lines)
  ```

  인과: Orca 주입 preamble의 어휘(worktree, terminal send, dispatch, handover)가 agent
  CLI에 설치된 `orca-cli` 스킬의 트리거 문구와 겹친다. 여기에 codex 전역
  `developer_instructions`의 `Follow AGENTS.md for skill/keyword routing`이 더해지면
  agent는 착수 전에 그 스킬을 로드하고 `skills get`으로 전체 레퍼런스까지 끌어와 예산을
  태운다. **모델 능력 문제도 spec 품질 문제도 아니다. 어휘 충돌이다.**

  대응 순서:

  1. spec 맨 앞에 instruction-source 가드를 넣는다 (`agent-contracts.md` §3).
     `run-stage.sh`가 자동으로 붙인다.
  2. 재시도 전에 `worker-tail`이 `skill-detour`를 냈는지 본다. 그렇다면 spec을 고치거나
     모델을 탓하기 전에 가드부터 확인한다.
  3. 가드가 있는데도 반복되면 그 agent를 그 단계에서 제외하고 Coordinator가 흡수한다.
     40분짜리 실패를 한 번 더 감수할 근거는 없다.

- **worker terminal이 과제 도중 죽어도 dispatch는 살아 있는 것처럼 보인다.** 실측
  2026-08-07: codex 터미널이 착수 49초 만에 사라졌는데(`dispatched 10:06:34 ->
  10:07:23`, heartbeat 없음, 메일 0건) `dispatch-show`의 status는 `failed`가 아니었고,
  단계는 420초를 끝까지 기다렸다. 더 빠르고 확실한 신호는 터미널 쪽이다:

  ```bash
  orca-ide orchestration worker-read --dispatch <id> --limit 1 --json
  # result.status.terminal == exited  -> 이 단계는 영원히 보고할 수 없다
  ```

  `run-stage.sh`가 폴링마다 이 둘을 함께 본다. 손으로 감독할 때도 timeout을 끝까지
  기다리기 전에 터미널 생존을 먼저 확인한다.

- **agent CLI가 Orca TUI 경로에서만 죽는 경우가 있다. CLI 자체 탓으로 단정하지 않는다.**
  위 사례에서 같은 codex를 비대화형으로 직접 실행하면 정상 동작했다
  (`codex exec ...` → 정답 출력, hook 정상, exit 0). 즉 CLI는 건강하고 Orca 터미널
  경로에서만 재현된다. 원인 미확정. 진단 순서는 **CLI 단독 실행 → Orca 경로** 이며,
  이 구분 없이 모델이나 spec을 바꾸면 엉뚱한 곳을 고치게 된다.

- **custom argv 경로에서는 `worker_done`이 거부될 수 있다.** 실측: `terminal
  create` + `dispatch --inject`로 띄운 OpenCode worker가 보낸 `worker_done`이
  `The Dispatch capability is missing for the given dispatch ID`로 거부됐다.
  `worker-start`로 띄운 Codex worker는 정상 처리됐다. 그러므로 모델 override가
  필요 없으면 항상 `worker-start`를 쓴다. custom argv가 필요해서 거부가 발생하면,
  §7의 report-file completion으로 닫는다. worker의 보고 없이 성공으로 간주하지
  않는다. 확인한 산출물 경로를 result에 남긴다.
- 같은 이유로 **custom argv worker는 `worker-release`로 종료되지 않을 수 있다.**
  `worker-release`는 proven identity의 coordinator-owned terminal만 닫고, 그 외에는
  `release_unknown`을 반환한다. 이때는 `terminal create`가 반환한 handle을 그대로
  써서 `terminal close --terminal <handle> --json`으로 닫는다. handle을 잃어버렸으면
  `terminal list`로 title(생성 시 지정한 stage 이름)을 맞춰 찾는다. 그래서 custom
  argv 경로에서는 `terminal create`의 handle을 반드시 `00-run.md`에 기록한다.

## 7. 로컬 worker 완료 규약 (report-file completion)

적용 조건: worker가 OpenCode이고 그 뒤의 모델이 **로컬 모델**(Ollama 등)일 때.
Codex·Claude worker는 §3의 `worker_done` 경로를 그대로 쓴다. 두 경로를 섞지 않는다.

근거 (실측, 2026-08-06):

- `qwen3:8b`(num_ctx 32768)는 `bash` 툴 호출과 파일 작성을 정상 수행했다. 그러나
  preamble의 완료 명령(`orchestration send --from … --dispatch-capability <64자>
  --type worker_done …`)은 완성된 리터럴 한 줄로 재주입해도 실행하지 못하고 턴을
  끝냈다. `gemma4:12b`도 동일하게 실패했다.
- `qwen2.5-coder:7b`는 더 나빴다. 툴 호출을 실제 tool_call이 아니라 평문
  `{"name": "bash", "arguments": …}`로 출력했다.

결론: 로컬 8B급 모델에 lifecycle 메시지 전송을 요구하지 않는다. 작업 수행 능력과
프로토콜 준수 능력은 별개다.

### 규약

1. Task spec의 마지막 단계는 **보고서 파일 작성 + sentinel 파일 생성**이다.
   sentinel 경로는 `<run_dir>/artifacts/done/<stage>.done`, 내용은 한 줄로
   `ok` 또는 `fail: <이유>`. 전송할 명령이 아니라 쓸 파일을 지시한다.
2. Coordinator는 로컬 stage 완료를 `check --wait`로 기다리지 않는다. 대신:

   ```bash
   scripts/wait-for-report.sh --done <run_dir>/artifacts/done/<stage>.done \
       --report <run_dir>/<stage-report>.md --timeout-sec 1800 --interval-sec 10
   ```

   exit 0이면 sentinel과 보고서가 모두 존재한다. exit 1은 timeout 또는
   sentinel만 있고 보고서가 빈 경우다.
3. **sentinel만 보고 성공으로 처리하지 않는다.** 보고서를 읽고
   `agent-contracts.md`의 해당 역할 출력 형식과 대조한다. 형식 불일치·필수 필드
   누락은 실패다.
4. **sentinel 직후에 바로 stop하지 않는다. 짧은 유예를 준다.** 실측: 로컬 worker가
   sentinel을 쓴 **뒤에** `worker_done`을 보내는 경우가 있다. sentinel만 보고 즉시
   `worker-stop`하면 그 `worker_done`이
   `The Dispatch capability is invalid`로 거부되고 Run 메일함에 rejected 메시지가
   남는다. sentinel이 확인되면 먼저 한 번만 짧게 기다린다.

   ```bash
   orca-ide orchestration check --wait --types worker_done,escalation \
       --timeout-ms 30000 --json
   ```

   - `worker_done`이 오면 §3 경로로 처리한다. Task는 자동 completed가 되므로
     `task-update`를 덧붙이지 않고, `worker-stop` 대신 `worker-release`를 쓴다.
     이렇게 하면 dispatch가 `retained`가 아니라 `released`로 정리된다.
   - 30초 안에 오지 않으면 5번의 stop-then-close 경로로 간다. 이 유예를 늘리지
     않는다. 로컬 worker의 `worker_done`은 보장되지 않는다.
5. **`worker_done`이 오지 않았을 때만 Coordinator가 Task를 닫는다. 순서는
   worker 종료 → Task 닫기.** `worker_done` 없이 끝난 Dispatch는 `ready` 상태로
   남는다. 이때:
   - `worker-release`는 거부된다 (`Dispatch ... is ready; only a succeeded or
     failed worker can release`). 대신 `worker-stop`을 쓴다.
   - Task를 먼저 completed로 바꾸고 나중에 `worker-stop`을 하면 **그 Task가 다시
     `blocked`로 되돌아간다** (실측). 반드시 `worker-stop` 다음에 `task-update`.

   ```bash
   orca-ide orchestration worker-stop --dispatch <dispatch_id> --json
   orca-ide orchestration task-update --id <task_id> --status completed \
       --result '{"report":"<abs report path>","closed_by":"coordinator"}' --json
   orca-ide orchestration task-list --run <run_id> --brief --json   # 상태 확인
   ```

   닫은 뒤 `task-list`로 status가 유지되는지 확인한다. Task status와 terminal
   상태는 별개다. sentinel이 `fail:`이거나 3번의 형식 검사에 실패하면
   `--status failed`로 닫고 §6의 correction 절차로 넘어간다.
6. timeout이면 실패로 단정하지 않는다. `worker-read`로 진행 상태를 먼저 확인하고,
   진전이 없을 때만 실패 처리한다.
7. 로컬 worker가 `worker_done`을 실제로 보냈다면 그것을 우선 수락하고 §3대로
   처리한다. 이 규약은 폴백이지 금지가 아니다. 실측: `gemma4-32k:12b`는 3단계
   spec에서는 보내지 못했지만, `terminal send`로 한 단계씩 밀어 준 뒤에는 정상
   `worker_done`을 보냈다.
8. **`worker_done` payload의 필드는 검증되지 않은 주장이다.** 실측:
   `filesModified`에 실제로는 수정되지 않은 파일이 들어 있었다. `outcome`,
   `filesModified`, `reportPath`를 근거로 쓰지 않는다. 파일 변경 여부는
   `build-context-manifest.py check`나 `git status`로, 테스트 결과는
   `run-captured.sh` 로그의 exit code로 Coordinator가 직접 확인한다.
9. **로컬 worker 보고서의 수치를 그대로 인용하지 않는다.** 실측: worker가
   `grep -c test`(괄호 유실)로 센 값을 `13 test cases`로 보고했으나 실제는 12였다.
   개수·크기·exit code는 Coordinator가 다시 센다.

### 환경 전제

아래를 만족하지 못하면 그 단계를 로컬에 배정하지 않고 사유를 `00-run.md`에 적는다.

1. `command -v opencode` 결과가 `/mnt/c/`로 시작하면 **안 된다**. 실측: Windows npm
   설치본은 cwd가 WSL 경로여도 bash 툴을 PowerShell에서 실행해 모든 Unix 명령이
   `CommandNotFoundException`으로 실패한다. WSL 네이티브 설치본이 PATH 앞에 있어야
   한다.
2. 로컬 모델의 실효 context가 32768 이상이어야 한다. 확인:

   ```bash
   curl -s http://127.0.0.1:11434/api/ps | python3 -m json.tool | grep -i context
   ```

   서버 기본값이 낮아도 Modelfile의 `PARAMETER num_ctx`가 우선하므로, 사용자에게
   그 방법을 제안할 수 있다. Skill이 Ollama나 OpenCode 설정을 임의로 바꾸지 않는다.
3. OpenCode의 subagent 툴이 꺼져 있어야 한다 (`tools.task=false`). 실측:
   `qwen3:8b`가 subagent를 무한 스폰하며 같은 작업을 반복했다.
4. **thinking 모델은 출력 예산이 넉넉해야 한다.** `limit.output`을 8192 이상으로
   둔다. 측정: `qwen3-32k:8b`에 같은 요청을 주고 `max_tokens`만 바꾼 결과.

   ```text
   max_tokens=  256  finish=length      tool_calls=0  reasoning=925자
   max_tokens= 1500  finish=tool_calls  tool_calls=2  reasoning=3164자
   max_tokens= 6000  finish=tool_calls  tool_calls=2  reasoning=2228자
   ```

   예산이 부족하면 reasoning이 전부 먹고 `finish_reason: length`로 끝나 툴 호출이
   0이 된다. 화면에는 `+ Thought: 7.4s` 뒤 아무 일도 없는 것으로 보인다. 턴당
   700~950 출력 토큰이 reasoning으로 나가므로 경계에 걸치면 산발적으로 실패한다.
5. **툴 호출 형식이 실제로 나오는 모델이어야 한다.** 측정: `qwen2.5-coder:7b`는
   프로브 7/7에서 tool_call 대신 평문을 냈다.

   ```text
   {"name": "bash", "arguments": {"command": "head -1 /etc/hostname"}}
   ```

   확률적 실수가 아니라 챗 템플릿이 OpenAI 형식 `tool_calls`를 만들지 않는 것이다.
   worker 후보에서 제외한다. 새 모델을 쓰기 전에 1단계 프로브로 이것부터 확인한다.
6. **worker 모델은 에러 회복률로 고른다. 파라미터 수나 토큰 속도로 고르지 않는다.**

   정상 경로 성능은 변별력이 없다. 실패할 수 없게 만든 spec에서는 후보들이 모두
   통과한다. 실제 Run에서 갈리는 순간은 예상 못 한 에러가 났을 때고, 그건 반드시
   일어난다. 측정: `edit`이 계속 실패하는 상황에서 목표 파일을 끝내 만들어 내는지,
   시행 10회, 온도를 통제한 비교.

   ```text
   모델                        완주    배회   중앙 턴   중앙 벽시계
   gemma4-32k:12b  temp 0     10/10     0        4        17s
   qwen3.5:9b      temp 0.6    4/10     5       12        37s
   qwen3.5:9b      temp 0      4/10     5       12        27s
   ```

   같은 비교에서 qwen3.5가 VRAM 6.6GB 대 8.1GB, 98.8 대 60.6 tok/s로 앞섰지만
   순위를 뒤집지 못했다. 턴을 3배 쓰기 때문에 토큰 속도 우위가 벽시계에서 사라진다.
   **원시 속도가 아니라 실패 후 몇 턴 만에 계획으로 돌아오는지가 비용을 정한다.**

   온도를 맞춰도 격차가 그대로라는 점이 중요하다. 이건 샘플링 설정으로 고칠 수 있는
   문제가 아니다.

   새 모델을 후보에 넣을 때는 위 세 전제(4·5번과 이 항목)를 같은 형태로 재측정하고
   결과를 `00-run.md`에 남긴다. n이 4 이하이거나 온도가 통제되지 않은 비교로 모델을
   바꾸지 않는다. 실측: n=4에 온도 미통제였던 1차 비교는 결론은 같았지만 근거로는
   불충분했다.
7. **긴 문자열 재현 정확도를 측정한다. 이것이 로컬 worker의 지배적 결함이다.**

   한 캠페인에서 관측된 훼손 다섯 건은 전부 같은 뿌리다 — 모델이 긴 문자열을 다시
   만들어 내는 순간이다.

   ```text
   Wiki-Root         -> Wiki_Root            문자 치환
   work/ProjectRoot  -> kem/Project          토큰 훼손
   Wiki-Root/Work    -> Wiki-Root/ Work      공백 삽입
   project()         -> project              문자 누락 (edit의 oldString)
   ba8bd24978b8      -> ba8wd24978b8         한 글자 치환
   ```

   증상은 각각 다르게 보인다. sentinel이 엉뚱한 디렉터리에 생기고, build/test 명령이
   무효가 되고, `edit`이 `oldString not found`로 반복 실패하고, 존재하지 않는 경로를
   참조해 권한 프롬프트에서 멈춘다. 원인은 하나다.

   길이 자체는 원인이 아니다. 144자짜리 단일 경로는 12/12 정확히 재현된다. 발화
   조건은 **구조**다. 인접한 두 경로가 접두사 관계일 때(짧은 것이 먼저) 무너진다.

   ```text
   케이스                            gemma4-32k   qwen3.5 9B   qwen3 8B
   단일 긴 경로                        10/10        10/10        7/10
   두 경로, 겹침 없음                   10/10        10/10       10/10
   두 경로, 접두사 겹침                  1/10        10/10       10/10
   같은 두 경로, 순서 반대               10/10        10/10       10/10
   세 경로, 겹침                        6/10        10/10       10/10
   ```

   순서를 뒤집으면(긴 것 먼저) 복구된다. 겹침이 없으면 인자가 둘이어도 안전하다.
   **모델별 차이가 크다** — 같은 조건에서 gemma4는 1/10, qwen3.5와 qwen3는 10/10이다.

   이 측정은 OpenCode를 거치지 않고 Ollama의 OpenAI 호환 엔드포인트를 직접 쳐서
   얻었다. 따라서 원인은 CLI 계층이 아니라 모델이다.

   **`edit` 실패도 이 결함의 한 증상이다.** OpenCode의 매처는 무죄다 — 실측 결과
   활성 경로는 관대한 쪽이고, 들여쓰기와 내부 공백 차이를 모두 흡수한다
   (정규화된 `oldString`으로 편집이 성공하고 원본 들여쓰기가 보존됐다).
   실패한 것은 `project()`를 `project`로 쓴 경우, 즉 공백이 아니라 코드 토큰이
   훼손된 경우였다. 어떤 replacer도 그것은 복구하지 못한다.
   에러 메시지가 *어디가* 다른지 알려주지 않으므로 모델은 자기가 옳다고 확신한 채
   같은 시도를 반복한다. 그래서 §3 spec 규칙이 `edit` 지시를 금지한다.
