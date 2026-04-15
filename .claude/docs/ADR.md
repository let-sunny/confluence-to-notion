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
