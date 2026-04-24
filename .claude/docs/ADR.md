# Architecture Decision Records

각 ADR은 Decision / Why / Impact 3줄. 상세 이력은 GitHub Wiki 참조.

## ADR-001: Multi-Agent Pipeline

- **Decision**: 패턴 발견 → 규칙 제안을 독립 에이전트로 분리. 현재 2-agent (Discovery + Proposer), Critic/Arbitrator는 필요시 추가.
- **Why**: 단일 프롬프트로 XHTML 분석 + 매핑 제안 + 검증을 동시에 하면 품질 저하. 에이전트별 책임 분리가 평가/개선 용이.
- **Impact**: JSON 파일 기반 통신 필수. `schemas.py`가 에이전트 간 계약. 토큰 사용량 증가하지만 재현성 확보.

## ADR-002: Script-Based Orchestration

- **Decision**: `claude -p` 호출을 bash 스크립트(`scripts/discover.sh`, `scripts/develop.sh`)로 오케스트레이션.
- **Why**: 파이프라인이 선형이므로 LLM 판단 불필요. 스크립트는 결정적이고 디버깅 가능. `--from N`으로 단계별 재시도.
- **Impact**: 에이전트 간 공유 컨텍스트 없음 — 파일 계약이 충분해야 함. 동적 라우팅 필요시 bash 조건문 추가.

## ADR-003: Circuit Breaker with Re-Plan Fallback

- **Decision**: develop.sh의 Fix 루프에 서킷브레이커 적용. OPEN 시 exit가 아니라 re-plan (다른 접근법 시도).
- **Why**: 같은 에러 반복 fix는 토큰 낭비. OPEN → re-plan → HALF_OPEN probe로 자동 복구 시도 후 실패시만 사람 개입.
- **Impact**: `output/dev/circuit.json`으로 상태 persist. `--from 5`가 HALF_OPEN 트리거.

## ADR-004: Eval as Signal, Not Merge Gate

- **Decision**: `tests/fixtures/eval/expected_*.json` rule_id 매칭은 회귀 감지 신호로만 사용. 머지 게이트로 쓰지 않음. 향후 의미적 커버리지 + LLM-as-judge로 재설계.
- **Why**: 같은 매크로도 문서 맥락에 따라 다양한 Notion 매핑이 자연스러움(N:M). 매크로 종류는 무한 확장(유저 플러그인) + LLM 출력의 rule_id 비결정성 때문에 정답표 enumerate는 본질적 한계.
- **Impact**: CLAUDE.md "프롬프트 변경 전 run-eval.sh" 규칙은 변경의 영향 가시화 용도로만 유지. PR 머지 결정에서 `partial`/낮은 F1을 자동 reject 사유로 쓰지 않음. Migration(#86): `compare_discovery`/`compare_proposer`, `EvalMatchResult`, `EvalReport.results`/`overall_pass`, `tests/fixtures/eval/expected_*.json` 를 제거 — eval은 semantic coverage + LLM-as-judge + baseline diff 로만 동작.

## ADR-005: Ambiguity → Ask Human → Persist as Rule

- **Decision**: 변환 모호성(테이블 vs DB, 매크로 N:M 매핑 등)은 자동 판정·휴리스틱으로 해결하지 않고 `rule lookup → 없으면 사람에게 질의 → 답을 규칙으로 저장`을 기본 흐름으로 한다. discover 파이프라인의 patterns→rules 모델을 신규 변환 기능에도 동일하게 적용.
- **Why**: Confluence는 회사·팀별 사용 패턴 차이가 커서 (커스텀 매크로, 자유로운 테이블 구조 등) 하드코딩 휴리스틱·LLM 단독 판정으로 일반화 불가. 사람이 한 번 결정한 룰은 같은 시그니처가 다시 나올 때 재사용되어 인터랙션 비용이 점근적으로 0으로 수렴.
- **Impact**: 새 기능 설계 시 자동 판정을 1순위로 제안하지 않음(보조 수단으로만). 룰 저장소 위치·key 시그니처·비대화형(CI) 실행 시 fallback 정책을 기능별로 명시. LLM은 룰 초안 제안 등 보조 역할.

## ADR-006: Eval as Merge Gate — Restored

- **Decision**: discover-pipeline 프롬프트(`pattern-discovery`, `rule-proposer`) 변경 PR 의 머지 게이트로 `scripts/run-eval.sh` 결과(schema validation + semantic coverage + LLM-as-judge + baseline diff)를 사용한다. ADR-004 의 '정답표 enumerate 한계' 결정은 보존하되, #84 (LLM-as-judge) / #85 (baseline snapshot) / #86 (fixture deprecate) 재설계 이후의 현 정책으로 ADR-004 를 supersede.
- **Why**: ADR-004 가 지적한 N:M 매핑·rule_id 비결정성 한계는 정답표 매칭 방식에 국한. 의미적 커버리지 + LLM-as-judge + baseline diff 조합은 개별 rule_id 에 묶이지 않고 변환 품질의 회귀를 잡을 수 있어 머지 게이트로 재사용 가능.
- **Impact**: CLAUDE.md Development Process 문구가 '머지 게이트' 로 복귀(이 ADR 참조). `.github/pull_request_template.md` 에 discover-pipeline 프롬프트 변경 여부 체크박스 + `eval_results/<timestamp>.json` 첨부 가이드 섹션 추가. 스코프는 discover-pipeline 한정 — 그 외 PR 은 'N/A (discover-pipeline 무관)' 표기 허용. 회귀 감지는 `scripts/run-eval.sh --fail-on-regression` 로 엄격 모드 지정 가능.

## Standalone ADRs

Decisions large enough to need their own file live alongside this index:

- [ADR-00N — Port to TypeScript](./ADR-00N-port-to-typescript.md) — hybrid port strategy, toolchain pin, package name, repo cutover plan.
- [ADR-00M — CLI surface freeze](./ADR-00M-cli-surface-freeze.md) — authoritative inventory of every `c2n` subcommand + flag that the TS rewrite must preserve.
