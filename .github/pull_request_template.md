## Summary

<!-- 1-3 bullet 로 변경 내용 요약. 관련 이슈를 `Closes #N` 으로 연결하면 머지 시 자동 클로즈. -->

-
-

Closes #

## Eval 리포트 (discover-pipeline 머지 게이트)

discover-pipeline 프롬프트(`.claude/agents/discover/pattern-discovery.md`, `.claude/agents/discover/rule-proposer.md`) 를 변경했는가?

- [ ] Yes — `bash scripts/run-eval.sh` 결과를 아래에 첨부. 기본 게이트: **schema validation + semantic coverage + baseline diff** (ADR-006 / CLAUDE.md 참조)
- [ ] No — N/A (discover-pipeline 무관)

변경 시 아래 요약을 채울 것:

- 리포트 파일: `eval_results/<timestamp>.json`
- Semantic coverage: <예: 0.92 (+0.01 vs baseline)>
- Baseline diff: <회귀 없음 | 회귀 항목 요약 + 판단 근거>
- LLM-judge (opt-in, `--llm-judge`): <예: avg 4.3 / 5, 샘플 수 N | 미실행>

> LLM-as-judge 는 API 비용 때문에 기본 off — 필요 시 `--llm-judge`. 회귀 차단을 엄격히 원하면 `--fail-on-regression`.

## 테스트 계획

- [ ] `uv run pytest`
- [ ] `uv run ruff check src/ tests/`
- [ ] `uv run mypy src/`
- [ ] (해당 시) 수동 검증 단계 명시:
